import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:url_launcher/url_launcher.dart';

import '../analysis/frame_decoder.dart';
import '../api/analysis_result.dart';
import '../api/pocket_drs_api.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../utils/app_logger.dart';
import '../utils/app_settings.dart';
import '../widgets/image_marker.dart';
import '../widgets/trajectory_video_view.dart';
import '../widgets/video_frame_selector.dart';
import '../widgets/video_trim_selector.dart';
import 'settings_screen.dart';

const _native = MethodChannel('pocket_drs/native');
// keep in step with the server's own upload limit
const _maxUploadBytes = 200 << 20;

/// Single end-to-end flow: pick one video → trim it → choose a frame → tap
/// both sets of stumps → the server tracks the ball on that same video and
/// returns a 3D trajectory we render.
class AnalyzeScreen extends StatefulWidget {
  const AnalyzeScreen({super.key});

  @override
  State<AnalyzeScreen> createState() => _AnalyzeScreenState();
}

enum _Step { upload, trim, frame, stumps, processing, results }

class _AnalyzeScreenState extends State<AnalyzeScreen> {
  final _picker = ImagePicker();

  _Step _step = _Step.upload;

  // Calibration inputs (one video drives everything).
  XFile? _video;
  Uint8List? _frameBytes;
  // Normalised striker TL, TR, BR, BL then bowler TL, TR, BR, BL.
  List<Offset>? _stumps;

  // Trimmed segment (whole clip by default). Backend honours these as
  // ``segment.{start_ms, end_ms}`` so it only decodes what the user
  // bracketed, keeps tracking work proportional to the delivery, not the
  // surrounding minutes of recording.
  int _segmentStartMs = 0;
  int _segmentEndMs = 600000;
  // Whether the source came from the camera roll's RECORD button (so we
  // can optionally delete it after analysis to save phone storage).
  bool _videoFromCamera = false;

  // Batsman handedness, sets which side is leg vs off for the LBW decision.
  // Sent as the request's ``batsman_handedness`` ('right' or 'left').
  String _batsmanHandedness = 'right';

  // Processing / result state.
  int? _progressPct;
  String? _progressStage;
  String? _progressError;
  AnalysisResult? _analysis;
  String? _jobId;
  // the result's times are on the cut's clock, so the result plays the cut
  String? _cutPath;
  // bumped on each analysis and on cancel, so a stale job can't land a result
  int _run = 0;
  // closed on cancel, so a dropped analysis stops uploading
  PocketDrsApi? _api;

  void _log(String m) => AppLogger.instance.log(m);

  // ---------------------------------------------------------------- step 1: video
  Future<void> _pickVideo(ImageSource source) async {
    try {
      final video = await _picker.pickVideo(source: source);
      if (video == null || !mounted) return;
      // no native trim on web, so a too-big file has to be caught before the
      // user spends time marking stumps on it
      if (kIsWeb && await video.length() > _maxUploadBytes) {
        _showError(
          'This video is over 200 MB. Trim it on your phone first, then '
          'pick it again.',
        );
        return;
      }
      setState(() {
        _video = video;
        _videoFromCamera = source == ImageSource.camera;
        _frameBytes = null;
        _stumps = null;
        _segmentStartMs = 0;
        _segmentEndMs = 600000;
        _step = _Step.trim;
      });
    } catch (_) {
      _showError("Couldn't open this video. Try another clip.");
    }
  }

  // ---------------------------------------------------------------- step 1.5: trim
  void _onTrimSelected(Duration start, Duration end) {
    setState(() {
      _segmentStartMs = start.inMilliseconds;
      _segmentEndMs = end.inMilliseconds;
      _step = _Step.frame;
    });
  }

  // ---------------------------------------------------------------- step 2: frame
  Future<bool> _onFrameSelected(Duration timestamp) async {
    final video = _video;
    if (video == null) return false;
    try {
      final bytes = await decodeFrameJpeg(
        videoPath: video.path,
        timeMs: timestamp.inMilliseconds,
        quality: 95,
      );
      if (bytes == null) {
        _showError("Couldn't read a frame from this clip. Try another one.");
        return false;
      }
      // the user went back while the frame was being read
      if (!mounted || _video != video || _step != _Step.frame) return true;
      setState(() {
        _frameBytes = bytes;
        _step = _Step.stumps;
      });
      return true;
    } catch (e, st) {
      _log('[FRAME] extraction failed: $e\n$st');
      _showError("Couldn't read a frame from this clip. Try another one.");
      return false;
    }
  }

  // ------------------------------------------------------------ analyse
  Future<void> _analyse() async {
    final video = _video;
    final stumps = _stumps;
    if (video == null || stumps == null) return;
    final run = ++_run;
    bool stale() => !mounted || run != _run;

    setState(() {
      _dropCut();
      _step = _Step.processing;
      _progressPct = 0;
      _progressStage = 'queued';
      _progressError = null;
    });

    final api = _api = PocketDrsApi(baseUrl: kServerUrl);
    String? cutPath;
    try {
      _log('[ANALYZE] server=$kServerUrl');
      var startMs = _segmentStartMs;
      var endMs = _segmentEndMs;
      final Uint8List bytes;
      if (kIsWeb) {
        bytes = await video.readAsBytes();
      } else {
        // upload only the marked segment, not the whole recording
        cutPath =
            '${Directory.systemTemp.path}/pocket_drs_cut_'
            '${DateTime.now().microsecondsSinceEpoch}.mp4';
        // the cut starts at a keyframe, so the chosen part sits at span[0] inside it
        final List<int>? span;
        try {
          span = await _native.invokeListMethod<int>('trim', {
            'input': video.path,
            'output': cutPath,
            'startMs': startMs,
            'endMs': endMs,
          });
        } catch (e) {
          final msg = e is PlatformException ? (e.message ?? e.code) : '$e';
          throw StateError('Could not cut the clip: $msg');
        }
        startMs = span![0];
        endMs = span[1];
        bytes = await File(cutPath).readAsBytes();
      }
      final jobId = await api.createJob(
        videoBytes: bytes,
        videoFilename: video.name,
        requestJson: jobRequest(
          stumps: stumps,
          handedness: _batsmanHandedness,
          startMs: startMs,
          endMs: endMs,
          maxFrames: 240,
          pitchLengthM: await AppSettings.getPitchLength(),
        ),
      );
      _log('[ANALYZE] job=$jobId');

      final analysis = await api.waitForResult(
        jobId,
        cancelled: stale,
        onStatus: (status) => setState(() {
          _progressPct = status.pct;
          _progressStage = status.stage ?? status.status;
          _progressError = status.errorMessage;
        }),
      );
      if (stale()) return;
      setState(() {
        _analysis = analysis;
        _jobId = jobId;
        _cutPath = cutPath;
        _step = _Step.results;
      });
    } catch (e) {
      _log('[ANALYZE] error: $e');
      if (stale()) return;
      // Most failures are calibration (re-mark stumps), drop back to the stump
      // step so the user can adjust and retry without restarting.
      setState(() => _step = _Step.stumps);
      _showError(switch (e) {
        ApiException e => e.message,
        StateError e => e.message,
        _ => 'Analysis failed. Try again.',
      });
    } finally {
      api.close();
      if (_api == api) _api = null;
      if (cutPath != null && cutPath != _cutPath) {
        File(cutPath).delete().ignore();
      }
    }
  }

  void _dropCut() {
    final cut = _cutPath;
    _cutPath = null;
    if (cut != null) File(cut).delete().ignore();
  }

  // checking again from the stumps step cuts the source again, so a recorded one goes only once the user leaves
  Future<void> _deleteRecordedSource() async {
    final video = _video;
    if (kIsWeb || video == null || !_videoFromCamera || _analysis == null) {
      return;
    }
    if (!await AppSettings.getAutoDeleteSource()) return;
    try {
      await File(video.path).delete();
    } catch (e) {
      _log('[ANALYZE] auto-delete failed: $e');
    }
  }

  @override
  void dispose() {
    _api?.close();
    _deleteRecordedSource();
    _dropCut();
    super.dispose();
  }

  void _restart() {
    _deleteRecordedSource();
    setState(() {
      _dropCut();
      _step = _Step.upload;
      _video = null;
      _videoFromCamera = false;
      _segmentStartMs = 0;
      _segmentEndMs = 600000;
      _frameBytes = null;
      _stumps = null;
      _progressPct = null;
      _progressStage = null;
      _progressError = null;
      _analysis = null;
      _jobId = null;
    });
  }

  void _back() {
    setState(() {
      switch (_step) {
        case _Step.trim:
          _step = _Step.upload;
          _video = null;
        case _Step.frame:
          _step = _Step.trim;
        case _Step.stumps:
          _step = _Step.frame;
          _frameBytes = null;
        case _Step.processing:
          _run++;
          _api?.close();
          _step = _Step.stumps;
        case _Step.results:
          _step = _Step.stumps;
        case _Step.upload:
          break;
      }
    });
  }

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(msg),
        duration: const Duration(seconds: 10),
        showCloseIcon: true,
      ),
    );
  }

  // -------------------------------------------------------------------- build
  static const _totalSteps = 4;

  String get _title => switch (_step) {
    _Step.upload => 'Choose a video',
    _Step.trim => 'Trim to the delivery',
    _Step.frame => 'Pick a clear frame',
    _Step.stumps => 'Mark the stumps',
    _Step.processing => 'Analysing',
    _Step.results => 'Result',
  };

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final isResults = _step == _Step.results;
    final isProcessing = _step == _Step.processing;
    final showProgress = !isResults && !isProcessing;

    return PopScope(
      // Route the Android hardware back button through the same one-stage
      // step-back the in-app arrow uses, so back never backgrounds/exits the
      // app mid-flow. At the first step (upload) there is nothing to step back
      // to, so canPop lets the OS handle the pop (exit).
      canPop: _step == _Step.upload,
      onPopInvokedWithResult: (didPop, result) {
        if (didPop) return;
        _back();
      },
      child: Scaffold(
        backgroundColor: isResults ? AppColors.video : scheme.surface,
        appBar: AppBar(
          automaticallyImplyLeading: false,
          leading: (_step != _Step.upload || Navigator.canPop(context))
              ? IconButton(
                  tooltip: 'Back',
                  onPressed: _step == _Step.upload
                      ? () => Navigator.pop(context)
                      : _back,
                  icon: const Icon(Icons.arrow_back),
                )
              : null,
          title: Text(_title),
          // on phones settings sit on the home screen; on web this is the home screen
          actions: kIsWeb && _step == _Step.upload
              ? [
                  IconButton(
                    tooltip: 'Settings',
                    icon: const Icon(Icons.settings_outlined),
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => const SettingsScreen(),
                      ),
                    ),
                  ),
                ]
              : null,
          bottom: showProgress
              ? PreferredSize(
                  preferredSize: const Size.fromHeight(4),
                  child: _StepProgress(value: (_step.index + 1) / _totalSteps),
                )
              : null,
        ),
        body: AnimatedSwitcher(
          duration: const Duration(milliseconds: 250),
          child: KeyedSubtree(key: ValueKey(_step), child: _body()),
        ),
      ),
    );
  }

  Widget _body() {
    switch (_step) {
      case _Step.upload:
        return _UploadStep(
          onPick: _pickVideo,
          handedness: _batsmanHandedness,
          onHandednessChanged: (h) => setState(() => _batsmanHandedness = h),
        );
      case _Step.trim:
        final v = _video;
        return v == null
            ? const SizedBox()
            : VideoTrimSelector(
                videoPath: v.path,
                onTrimSelected: _onTrimSelected,
              );
      case _Step.frame:
        final v = _video;
        return v == null
            ? const SizedBox()
            : VideoFrameSelector(
                videoPath: v.path,
                onFrameSelected: _onFrameSelected,
              );
      case _Step.stumps:
        return StumpMarker(
          frame: _frameBytes!,
          initialMarkers: _stumps,
          onComplete: (m) {
            setState(() => _stumps = m);
            _analyse();
          },
        );
      case _Step.processing:
        return _ProcessingView(
          pct: _progressPct,
          stage: _progressStage,
          error: _progressError,
        );
      case _Step.results:
        return ResultsView(
          videoPath: _cutPath ?? _video!.path,
          result: _analysis!,
          jobId: _jobId!,
          action: FilledButton.icon(
            icon: const Icon(Icons.refresh),
            label: const Text('Check another ball'),
            onPressed: _restart,
          ),
        );
    }
  }
}

/// Thin bar under the AppBar showing progress through the 4 upload/trim/
/// frame/stumps steps. Glides to the new value instead of jumping.
class _StepProgress extends StatelessWidget {
  const _StepProgress({required this.value});
  final double value;

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: value),
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeInOut,
      builder: (context, v, _) => LinearProgressIndicator(value: v),
    );
  }
}

class _UploadStep extends StatelessWidget {
  const _UploadStep({
    required this.onPick,
    required this.handedness,
    required this.onHandednessChanged,
  });
  final void Function(ImageSource) onPick;
  final String handedness;
  final void Function(String) onHandednessChanged;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: IntrinsicHeight(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Spacer(),
                Text('Pick a delivery', style: theme.textTheme.headlineSmall),
                const SizedBox(height: AppSpacing.md),
                Text(
                  'Record or choose one clip of the delivery. You trim it to the ball, '
                  'then mark the stumps on one frame.',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
                ),
                const Spacer(),
                Text(
                  'Batter',
                  style: theme.textTheme.labelLarge?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
                ),
                const SizedBox(height: AppSpacing.sm),
                SizedBox(
                  width: double.infinity,
                  child: SegmentedButton<String>(
                    expandedInsets: EdgeInsets.zero,
                    segments: const [
                      ButtonSegment(
                        value: 'right',
                        label: Text('Right-handed'),
                      ),
                      ButtonSegment(value: 'left', label: Text('Left-handed')),
                    ],
                    selected: {handedness},
                    onSelectionChanged: (s) => onHandednessChanged(s.first),
                  ),
                ),
                const SizedBox(height: AppSpacing.xl),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    icon: const Icon(Icons.videocam_outlined),
                    label: const Text('Record video'),
                    onPressed: () => onPick(ImageSource.camera),
                  ),
                ),
                const SizedBox(height: AppSpacing.md),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    icon: const Icon(Icons.video_library_outlined),
                    label: const Text('Choose from phone'),
                    onPressed: () => onPick(ImageSource.gallery),
                  ),
                ),
                const SizedBox(height: AppSpacing.xl),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ProcessingView extends StatelessWidget {
  const _ProcessingView({
    required this.pct,
    required this.stage,
    required this.error,
  });
  final int? pct;
  final String? stage;
  final String? error;

  // Friendly description for each backend stage. The backend emits short
  // tokens like "decode" / "tracking"; the user wants to see what is
  // actually happening at that moment instead of guessing.
  static const Map<String, String> _stageHelp = {
    'queued': 'Waiting in line',
    'starting': 'Loading the video',
    'decode': 'Reading frames from your clip',
    'calibration': 'Reading your stump marks',
    'tracking': 'Finding the ball in every frame',
    'reconstruction': "Working out the ball's path",
    'lbw': 'Making the LBW call',
    'finalize': 'Finishing up',
    'succeeded': 'Done',
    'failed': 'Failed',
  };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final p = (pct ?? 0).clamp(0, 100);
    final stageKey = (stage ?? 'working').toLowerCase();
    final stageName = stageKey.isEmpty
        ? stageKey
        : stageKey[0].toUpperCase() + stageKey.substring(1);
    final help = _stageHelp[stageKey] ?? 'Processing your delivery';
    final hasError = error != null;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              '$p%',
              style: AppTheme.tabular(
                theme.textTheme.displayMedium,
              )?.copyWith(color: hasError ? scheme.error : scheme.primary),
            ),
            const SizedBox(height: AppSpacing.md),
            Text(stageName, style: theme.textTheme.titleMedium),
            const SizedBox(height: AppSpacing.xs),
            Text(
              help,
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: scheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            // Determinate bar when the backend has emitted a percent, animated
            // indeterminate bar otherwise, so the user always sees motion and
            // can tell the difference between "stuck at this percent" and
            // "still working but no measurable progress yet".
            SizedBox(
              width: 240,
              child: TweenAnimationBuilder<double>(
                tween: Tween(begin: 0, end: pct == null ? 0 : p / 100.0),
                duration: const Duration(milliseconds: 300),
                curve: Curves.easeInOut,
                builder: (context, v, _) => LinearProgressIndicator(
                  value: pct == null ? null : v,
                  color: hasError ? scheme.error : scheme.primary,
                  backgroundColor: scheme.surfaceContainerHigh,
                  borderRadius: BorderRadius.circular(AppRadius.sm),
                ),
              ),
            ),
            if (hasError) ...[
              const SizedBox(height: AppSpacing.lg),
              Icon(Icons.error_outline, color: scheme.error, size: 28),
              const SizedBox(height: AppSpacing.sm),
              Text(
                error!,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall?.copyWith(color: scheme.error),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class ResultsView extends StatelessWidget {
  const ResultsView({
    super.key,
    required this.videoPath,
    required this.result,
    required this.jobId,
    required this.action,
  });
  final String videoPath;
  final AnalysisResult result;
  final String jobId;
  final Widget action;

  Future<void> _open3D(BuildContext context) async {
    try {
      final baseUri = Uri.parse(
        kServerUrl.endsWith('/') ? kServerUrl : '$kServerUrl/',
      );
      final uri = baseUri.resolve('v1/jobs/$jobId/three-d');
      final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!opened) throw StateError('no browser');
    } catch (_) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Could not open the 3D view. Is a web browser installed?'),
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final lbw = result.lbw;
    final size = MediaQuery.sizeOf(context);
    final wide = size.width > size.height;
    final video = Expanded(
      child: ColoredBox(
        color: AppColors.video,
        child: SafeArea(
          bottom: false,
          child: TrajectoryVideoView(videoPath: videoPath, result: result),
        ),
      ),
    );
    final panel = _ResultPanel(
      wide: wide,
      decision: lbw?.decision,
      // the server's warnings explain a missing call or a missing number
      reason: [if (lbw != null) lbw.reason, ...result.warnings]
          .where((l) => l.isNotEmpty)
          .map((l) => l[0].toUpperCase() + l.substring(1))
          .join('\n'),
      // the 3D page needs the fitted path, which only comes with a call
      onOpen3D: lbw == null ? null : () => _open3D(context),
      action: action,
    );
    // on a tripod the phone is often sideways, where a panel under the video would leave it no room
    return wide
        ? Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [video, SizedBox(width: 360, child: panel)],
          )
        : Column(
            children: [
              video,
              ConstrainedBox(
                constraints: BoxConstraints(maxHeight: size.height * 0.55),
                child: panel,
              ),
            ],
          );
  }
}

/// Verdict banner, reason and actions under the video. Fades in once so the
/// result doesn't just pop into place.
class _ResultPanel extends StatelessWidget {
  const _ResultPanel({
    required this.wide,
    required this.decision,
    required this.reason,
    required this.onOpen3D,
    required this.action,
  });

  final bool wide;
  final LbwDecisionKey? decision;
  final String reason;
  final VoidCallback? onOpen3D;
  final Widget action;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final verdictText = switch (decision) {
      LbwDecisionKey.out => 'Out',
      LbwDecisionKey.notOut => 'Not out',
      LbwDecisionKey.umpiresCall => "Umpire's call",
      null => 'No call',
    };
    final verdictColor = switch (decision) {
      LbwDecisionKey.out => AppColors.out(Brightness.light),
      LbwDecisionKey.notOut => AppColors.notOut(Brightness.light),
      LbwDecisionKey.umpiresCall => AppColors.umpiresCall(Brightness.light),
      null => scheme.surfaceContainerHighest,
    };
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeOut,
      builder: (context, t, child) => Opacity(opacity: t, child: child),
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: scheme.surfaceContainerLow,
          borderRadius: wide
              ? const BorderRadius.horizontal(
                  left: Radius.circular(AppRadius.xl),
                )
              : const BorderRadius.vertical(
                  top: Radius.circular(AppRadius.xl),
                ),
        ),
        child: SafeArea(
          top: wide,
          left: false,
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.xl,
              AppSpacing.lg,
              AppSpacing.xl,
              AppSpacing.lg,
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(
                    vertical: AppSpacing.md,
                    horizontal: AppSpacing.lg,
                  ),
                  decoration: BoxDecoration(
                    color: verdictColor,
                    borderRadius: BorderRadius.circular(AppRadius.md),
                  ),
                  child: Text(
                    verdictText,
                    textAlign: TextAlign.center,
                    style: theme.textTheme.headlineSmall?.copyWith(
                      color: decision == null ? scheme.onSurface : Colors.white,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
                const SizedBox(height: AppSpacing.md),
                if (reason.isNotEmpty) ...[
                  Text(reason, style: theme.textTheme.bodyLarge),
                  const SizedBox(height: AppSpacing.lg),
                ],
                if (onOpen3D != null) ...[
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      icon: const Icon(Icons.view_in_ar_outlined),
                      label: const Text('View in 3D'),
                      onPressed: onOpen3D,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                ],
                SizedBox(width: double.infinity, child: action),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
