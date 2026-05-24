import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';

import '../analysis/frame_decoder.dart';
import '../analysis/pitch_calibration.dart';
import '../api/analysis_result.dart';
import '../api/pocket_drs_api.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../utils/app_logger.dart';
import '../utils/app_settings.dart';
import '../widgets/drs_button.dart';
import '../utils/web_open.dart';
import '../widgets/image_marker.dart';
import '../widgets/trajectory_video_view.dart';
import '../widgets/video_frame_selector.dart';
import '../widgets/video_trim_selector.dart';
import 'settings_screen.dart';

/// Single end-to-end flow: pick one video → choose a frame → tap pitch corners
/// and both sets of stumps → enter the real pitch size → the server tracks the
/// ball on that same video and returns a 3D trajectory we render. No saved
/// pitches, no second upload, no trimming, no ball photo.
class AnalyzeScreen extends StatefulWidget {
  const AnalyzeScreen({super.key});

  @override
  State<AnalyzeScreen> createState() => _AnalyzeScreenState();
}

enum _Step {
  upload,
  trim,
  frame,
  pitch,
  stumpsStriker,
  stumpsBowler,
  processing,
  results,
}

class _AnalyzeScreenState extends State<AnalyzeScreen> {
  final _picker = ImagePicker();

  _Step _step = _Step.upload;

  // Calibration inputs (one video drives everything).
  XFile? _video;
  String? _framePath;
  Uint8List? _frameBytes;
  ui.Size? _frameSize;
  List<Offset>? _corners; // normalized [0..1], striker-L, striker-R, bowler-R, bowler-L
  List<Offset>? _strikerStumps; // normalized: [base, top]
  List<Offset>? _bowlerStumps; // normalized: [base, top]
  // Pitch length is geometry-fit on the server from the stump marks.
  // Width barely affects the ball reconstruction; a regulation default
  // is sent so the in-line LBW corridor renders at the right scale.
  static const double _pitchWidthM = 3.05;

  // Trimmed segment (whole clip by default). Backend honours these as
  // ``segment.{start_ms, end_ms}`` so it only decodes what the user
  // bracketed — keeps tracking work proportional to the delivery, not the
  // surrounding minutes of recording.
  int _segmentStartMs = 0;
  int _segmentEndMs = 600000;
  // Whether the source came from the camera roll's RECORD button (so we
  // can optionally delete it after analysis to save phone storage).
  bool _videoFromCamera = false;

  // Processing / result state.
  int? _progressPct;
  String? _progressStage;
  String? _progressError;
  AnalysisResult? _analysis;
  String? _jobId;
  String? _decision;
  String? _decisionReason;

  void _log(String m) => AppLogger.instance.log(m);

  // ---------------------------------------------------------------- step 1: video
  Future<void> _pickVideo(ImageSource source) async {
    try {
      final video = await _picker.pickVideo(source: source);
      if (video == null || !mounted) return;
      setState(() {
        _video = video;
        _videoFromCamera = source == ImageSource.camera;
        _framePath = null;
        _frameBytes = null;
        _segmentStartMs = 0;
        _segmentEndMs = 600000;
        _step = _Step.trim;
      });
    } catch (_) {
      _showError('Failed to load video');
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
  Future<void> _onFrameSelected(Duration timestamp) async {
    final video = _video;
    if (video == null) return;
    try {
      final bytes = await decodeFrameJpeg(
        videoPath: video.path,
        timeMs: timestamp.inMilliseconds,
        quality: 95,
      );
      if (bytes == null) {
        _showError('Failed to extract frame');
        return;
      }
      // dart:io File is a stub on Flutter web — keep the frame in memory
      // there, and only persist to a temp file on native platforms where
      // downstream code may still want a path (image_picker debug, etc.).
      String? framePath;
      if (!kIsWeb) {
        final tempDir = await getTemporaryDirectory();
        framePath = '${tempDir.path}/cal_${timestamp.inMilliseconds}.jpg';
        await File(framePath).writeAsBytes(bytes);
      }
      final size = await _decodeImageSizeFromBytes(bytes);
      if (!mounted) return;
      setState(() {
        _framePath = framePath;
        _frameBytes = Uint8List.fromList(bytes);
        _frameSize = size;
        _step = _Step.pitch;
      });
    } catch (e, st) {
      _log('[FRAME] extraction failed: $e\n$st');
      _showError('Frame extraction failed');
    }
  }

  Future<ui.Size> _decodeImageSizeFromBytes(List<int> bytes) async {
    final codec = await ui.instantiateImageCodec(Uint8List.fromList(bytes));
    final frame = await codec.getNextFrame();
    final size = ui.Size(
      frame.image.width.toDouble(),
      frame.image.height.toDouble(),
    );
    frame.image.dispose();
    return size;
  }

  Future<ui.Size> _decodeImageSize(String path) async {
    final bytes = await File(path).readAsBytes();
    final codec = await ui.instantiateImageCodec(bytes);
    final frame = await codec.getNextFrame();
    final size = ui.Size(
      frame.image.width.toDouble(),
      frame.image.height.toDouble(),
    );
    frame.image.dispose();
    return size;
  }

  // ---------------------------------------------------------------- step 3: pitch
  void _onPitchComplete(List<Offset> markers) {
    setState(() {
      _corners = markers;
      _step = _Step.stumpsStriker;
    });
  }

  // ------------------------------------------------------------ step 4/5: stumps
  // Four taps per end define the bounding rectangle of the 3-stump cluster:
  // top-left, top-right, bottom-right, bottom-left. World coords place those
  // at (X, ±OUTER_STUMP_HALF, {h, 0}) so the eight stump corner points (4 per
  // side) become an over-constrained PnP input — each side alone fully
  // determines the camera pose, the joint fit averages out tap noise.
  bool _validateStumpQuad(List<Offset> q, String endName) {
    if (q.length != 4) {
      _showError('Tap all 4 corners of the $endName stump cluster');
      return false;
    }
    final tl = q[0], tr = q[1], br = q[2], bl = q[3];
    final topY = (tl.dy + tr.dy) / 2.0;
    final bottomY = (br.dy + bl.dy) / 2.0;
    if (topY >= bottomY) {
      _showError(
          'For the $endName stumps: tap top-left, top-right, bottom-right, bottom-left in that order');
      return false;
    }
    final leftX = (tl.dx + bl.dx) / 2.0;
    final rightX = (tr.dx + br.dx) / 2.0;
    if (leftX >= rightX) {
      _showError(
          'For the $endName stumps: tap top-left, top-right, bottom-right, bottom-left in that order');
      return false;
    }
    return true;
  }

  void _onStrikerStumpsComplete(List<Offset> markers) {
    if (!_validateStumpQuad(markers, 'striker (far)')) return;
    setState(() {
      _strikerStumps = markers;
      _step = _Step.stumpsBowler;
    });
  }

  void _onBowlerStumpsComplete(List<Offset> markers) {
    if (!_validateStumpQuad(markers, 'bowler (near)')) return;
    setState(() => _bowlerStumps = markers);
    // Pitch length is derived server-side from the stump height, so there is
    // nothing more to enter — go straight to analysis.
    _analyse();
  }

  List<List<Offset>> _stumpGuides() {
    final c = _corners;
    if (c == null || c.length != 4) return const [];
    return <List<Offset>>[
      <Offset>[c[0], c[1], c[2], c[3], c[0]], // pitch outline
      <Offset>[c[0], c[1]], // striker line
      <Offset>[c[3], c[2]], // bowler line
    ];
  }

  // ------------------------------------------------------------ analyse
  PitchCalibration _buildCalibration() {
    final size = _frameSize!;
    Offset px(Offset n) => Offset(n.dx * size.width, n.dy * size.height);
    final corners = _corners!;
    final stumps = <Offset>[
      ..._strikerStumps!,
      ..._bowlerStumps!,
    ];
    return PitchCalibration(
      imagePoints: corners.map(px).toList(growable: false),
      stumpPoints: stumps.map(px).toList(growable: false),
      imageSizePx: size,
      imagePointsNorm: List<Offset>.unmodifiable(corners),
      stumpPointsNorm: List<Offset>.unmodifiable(stumps),
    );
  }

  Future<void> _analyse() async {
    final video = _video;
    if (video == null || _corners == null || _frameSize == null) return;

    final calibration = _buildCalibration();
    final platformName = Theme.of(context).platform.name;
    setState(() {
      _step = _Step.processing;
      _progressPct = 0;
      _progressStage = 'queued';
      _progressError = null;
    });

    try {
      final serverUrl = await AppSettings.getServerUrl();
      _log('[ANALYZE] server=$serverUrl');
      final api = PocketDrsApi(
        baseUrl: serverUrl,
        getAuthToken: () async {
          final user = FirebaseAuth.instance.currentUser;
          if (user == null) return null;
          try {
            return await user.getIdToken();
          } catch (_) {
            return null;
          }
        },
      );

      final cornersNorm = calibration.imagePointsNorm!
          .map((p) => <String, Object?>{'x': p.dx, 'y': p.dy})
          .toList(growable: false);
      // Each stump set is 4 taps forming the bounding rectangle of the
      // cluster: [top-left, top-right, bottom-right, bottom-left]. The
      // bottom pair sits at z=0 (ground), the top pair at z=stump_height.
      final sk = _strikerStumps!;
      final bw = _bowlerStumps!;
      Map<String, Object?> pt(Offset o) => {'x': o.dx, 'y': o.dy};
      final requestJson = <String, Object?>{
        'client': <String, Object?>{
          'platform': platformName,
          'app_version': 'dev',
        },
        'segment': <String, Object?>{
          'start_ms': _segmentStartMs,
          'end_ms': _segmentEndMs,
        },
        'calibration': <String, Object?>{
          'mode': 'taps',
          'pitch_corners_norm': cornersNorm,
          'stump_quads_norm': <Map<String, Object?>>[
            pt(sk[0]), pt(sk[1]), pt(sk[2]), pt(sk[3]),
            pt(bw[0]), pt(bw[1]), pt(bw[2]), pt(bw[3]),
          ],
          // Only width is sent — pitch length is geometry-fit on the
          // server from the marked stump rectangle so non-regulation
          // indoor / practice nets are handled correctly out of the box.
          'pitch_dimensions_m': <String, Object?>{'width': _pitchWidthM},
        },
        'tracking': <String, Object?>{'sample_fps': 60, 'max_frames': 180},
      };

      final bytes = await video.readAsBytes();
      final jobId = await api.createJob(
        videoBytes: bytes,
        videoFilename: video.name,
        requestJson: requestJson,
      );
      _log('[ANALYZE] job=$jobId');

      final analysis = await _pollUntilDone(api, jobId);
      if (!analysis.worldTrajectory.hasTrajectory) {
        throw StateError(
          'No ball track recovered. The ball may not be clearly visible, or '
          'the pitch corners/stumps need re-marking with the real pitch size.',
        );
      }
      final decision = switch (analysis.lbw?.decision) {
        LbwDecisionKey.out => 'out',
        LbwDecisionKey.notOut => 'not_out',
        LbwDecisionKey.umpiresCall => 'umpires_call',
        _ => null,
      };
      // Storage cleanup — only fires when the user has opted in AND the
      // clip came from in-app recording. A user-picked file from the
      // camera roll is theirs to keep; we never touch it.
      if (!kIsWeb && _videoFromCamera &&
          await AppSettings.getAutoDeleteSource()) {
        try {
          await File(video.path).delete();
          _log('[ANALYZE] deleted recorded source ${video.path}');
        } catch (e) {
          _log('[ANALYZE] auto-delete failed: $e');
        }
      }

      if (!mounted) return;
      setState(() {
        _analysis = analysis;
        _jobId = jobId;
        _decision = decision;
        _decisionReason = analysis.lbw?.reason;
        _step = _Step.results;
      });
    } catch (e) {
      _log('[ANALYZE] error: $e');
      if (!mounted) return;
      // Most failures are calibration (re-mark stumps) — drop back to the stump
      // step so the user can adjust and retry without restarting.
      setState(() => _step = _Step.stumpsBowler);
      _showError(e is ApiException ? e.message : 'Analysis failed: $e');
    }
  }

  Future<AnalysisResult> _pollUntilDone(PocketDrsApi api, String jobId) async {
    const maxPolls = 240;
    const maxTransient = 8;
    var transient = 0;
    for (var poll = 0; poll < maxPolls; poll++) {
      if (!mounted) throw StateError('Cancelled');
      final JobStatus status;
      try {
        status = await api.getJobStatus(jobId);
      } catch (e) {
        if (e is StateError) rethrow;
        if (++transient >= maxTransient) {
          throw StateError('Lost connection to server while analysing');
        }
        await Future.delayed(const Duration(seconds: 1));
        continue;
      }
      if (mounted) {
        setState(() {
          _progressPct = status.pct;
          _progressStage = status.stage ?? status.status;
          _progressError = status.errorMessage;
        });
      }
      if (status.status == 'succeeded') return api.getJobResult(jobId);
      if (status.status == 'failed') {
        throw StateError(status.errorMessage ?? 'Server analysis failed');
      }
      final ms = poll < 10 ? 500 : (poll < 30 ? 800 : 1200);
      await Future.delayed(Duration(milliseconds: ms));
    }
    throw StateError('Analysis timed out');
  }

  void _restart() {
    setState(() {
      _step = _Step.upload;
      _video = null;
      _videoFromCamera = false;
      _segmentStartMs = 0;
      _segmentEndMs = 600000;
      _framePath = null;
      _frameBytes = null;
      _frameSize = null;
      _corners = null;
      _strikerStumps = null;
      _bowlerStumps = null;
      _progressPct = null;
      _progressStage = null;
      _progressError = null;
      _analysis = null;
      _jobId = null;
      _decision = null;
      _decisionReason = null;
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
        case _Step.pitch:
          _step = _Step.frame;
          _framePath = null;
          _frameBytes = null;
        case _Step.stumpsStriker:
          _step = _Step.pitch;
          _corners = null;
        case _Step.stumpsBowler:
          _step = _Step.stumpsStriker;
          _strikerStumps = null;
        case _Step.upload:
        case _Step.processing:
        case _Step.results:
          break;
      }
    });
  }

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  // -------------------------------------------------------------------- build
  static const _labels = ['UPLOAD', 'TRIM', 'FRAME', 'PITCH', 'STRIKER', 'BOWLER'];

  String? get _hint => switch (_step) {
        _Step.pitch => 'Tap the 4 pitch corners, clockwise from the striker end.',
        _Step.stumpsStriker ||
        _Step.stumpsBowler =>
          'Tap the stump base first, then the top. Pinch to zoom.',
        _ => null,
      };

  /// Which side of the frame the currently-selected stump cluster sits on,
  /// derived from the already-tapped pitch corners. Returns null for steps
  /// where there is no "active cluster" (pitch / upload / etc), in which
  /// case the header falls back to its default left-aligned layout.
  ///
  /// The header (title + hint) is then aligned to that same side so it
  /// never floats over the empty half of the screen while the user is
  /// looking at — and tapping into — the loaded half.
  bool? get _activeClusterIsRight {
    final c = _corners;
    if (c == null || c.length != 4) return null;
    final double clusterX = switch (_step) {
      _Step.stumpsStriker => (c[0].dx + c[1].dx) / 2.0,
      _Step.stumpsBowler => (c[2].dx + c[3].dx) / 2.0,
      _ => double.nan,
    };
    if (clusterX.isNaN) return null;
    return clusterX >= 0.5;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final isResults = _step == _Step.results;
    final isProcessing = _step == _Step.processing;
    final hint = _hint;
    final showHeader = !isResults && !isProcessing;
    final clusterRight = _activeClusterIsRight;
    final alignRight = clusterRight == true;
    final textAlign = alignRight ? TextAlign.right : TextAlign.left;
    final colAlign =
        alignRight ? CrossAxisAlignment.end : CrossAxisAlignment.start;
    final titlePadding = alignRight
        ? const EdgeInsets.only(right: AppSpacing.md)
        : const EdgeInsets.only(left: AppSpacing.md);

    return Scaffold(
      backgroundColor: isResults ? AppColors.inkBlack : scheme.surface,
      appBar: showHeader
          ? PreferredSize(
              // Title + step bar + 2-line hint comfortably fit in ~140 px;
              // give a little headroom so 2-line ellipsis doesn't clip the
              // bottom of the second line on dense locales/font scales.
              preferredSize: Size.fromHeight(
                (hint != null ? 140 : 96) + MediaQuery.of(context).padding.top,
              ),
              child: SafeArea(
                bottom: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(
                    AppSpacing.sm,
                    AppSpacing.xs,
                    AppSpacing.lg,
                    AppSpacing.md,
                  ),
                  child: Column(
                    crossAxisAlignment: colAlign,
                    children: [
                      Row(
                        children: [
                          if (_step != _Step.upload)
                            IconButton(
                              onPressed: _back,
                              icon: const Icon(Icons.arrow_back, size: 20),
                            )
                          else
                            const SizedBox(width: AppSpacing.sm),
                          Text(
                            'STEP ${(_step.index + 1).toString().padLeft(2, '0')} / '
                            '${_labels.length.toString().padLeft(2, '0')}',
                            style: theme.textTheme.labelSmall
                                ?.copyWith(color: scheme.onSurfaceVariant),
                          ),
                          const Spacer(),
                          IconButton(
                            onPressed: () => Navigator.of(context).push(
                              MaterialPageRoute<void>(
                                builder: (_) => const SettingsScreen(),
                              ),
                            ),
                            icon: const Icon(Icons.settings_outlined, size: 20),
                          ),
                        ],
                      ),
                      Padding(
                        padding: titlePadding,
                        child: Text(
                          _labels[_step.index].toLowerCase().replaceFirstMapped(
                              RegExp(r'^.'), (m) => m.group(0)!.toUpperCase()),
                          style: theme.textTheme.headlineSmall,
                          textAlign: textAlign,
                        ),
                      ),
                      const SizedBox(height: AppSpacing.md),
                      _StepBar(current: _step.index, total: _labels.length),
                      if (hint != null) ...[
                        const SizedBox(height: AppSpacing.md),
                        Padding(
                          padding: titlePadding,
                          child: Text(
                            hint,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            textAlign: textAlign,
                            style: theme.textTheme.bodySmall
                                ?.copyWith(color: scheme.onSurfaceVariant),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            )
          : null,
      body: _body(),
    );
  }

  Widget _body() {
    switch (_step) {
      case _Step.upload:
        return _UploadStep(onPick: _pickVideo);
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
      case _Step.pitch:
        if (_frameBytes == null && _framePath == null) return const SizedBox();
        return ImageMarker(
                key: const ValueKey('pitch'),
                imagePath: _framePath,
                imageBytes: _frameBytes,
                maxMarkers: 4,
                title: 'Mark Pitch Corners',
                subtitle: 'Tap clockwise from the striker end',
                markerLabels: const [
                  'Striker Left',
                  'Striker Right',
                  'Bowler Right',
                  'Bowler Left',
                ],
                initialMarkers: _corners,
                showHeader: false,
                onComplete: _onPitchComplete,
              );
      case _Step.stumpsStriker:
        if (_frameBytes == null && _framePath == null) return const SizedBox();
        return ImageMarker(
                key: const ValueKey('striker'),
                imagePath: _framePath,
                imageBytes: _frameBytes,
                maxMarkers: 4,
                title: 'Mark Striker Stumps',
                subtitle: 'Tap the 4 corners of the stump cluster — top-left, top-right, bottom-right, bottom-left',
                markerLabels: const [
                  'Top Left', 'Top Right', 'Bottom Right', 'Bottom Left',
                ],
                initialMarkers: _strikerStumps,
                guides: _stumpGuides(),
                highlightGuideIndex: 1,
                showHeader: false,
                onComplete: _onStrikerStumpsComplete,
              );
      case _Step.stumpsBowler:
        if (_frameBytes == null && _framePath == null) return const SizedBox();
        return ImageMarker(
                key: const ValueKey('bowler'),
                imagePath: _framePath,
                imageBytes: _frameBytes,
                maxMarkers: 4,
                title: 'Mark Bowler Stumps',
                subtitle: 'Tap the 4 corners of the stump cluster — top-left, top-right, bottom-right, bottom-left',
                markerLabels: const [
                  'Top Left', 'Top Right', 'Bottom Right', 'Bottom Left',
                ],
                initialMarkers: _bowlerStumps,
                guides: _stumpGuides(),
                highlightGuideIndex: 2,
                showHeader: false,
                onComplete: _onBowlerStumpsComplete,
              );
      case _Step.processing:
        return _ProcessingView(
          pct: _progressPct,
          stage: _progressStage,
          error: _progressError,
        );
      case _Step.results:
        return _ResultsView(
          videoPath: _video!.path,
          result: _analysis!,
          decision: _decision,
          reason: _decisionReason,
          jobId: _jobId,
          onRestart: _restart,
        );
    }
  }
}

class _StepBar extends StatelessWidget {
  const _StepBar({required this.current, required this.total});
  final int current;
  final int total;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return SizedBox(
      height: 4,
      child: Row(
        children: List.generate(total, (i) {
          return Expanded(
            child: Container(
              margin: EdgeInsets.only(right: i == total - 1 ? 0 : 2),
              color: i <= current
                  ? AppColors.signalRed
                  : scheme.surfaceContainerHigh,
            ),
          );
        }),
      ),
    );
  }
}

class _UploadStep extends StatelessWidget {
  const _UploadStep({required this.onPick});
  final void Function(ImageSource) onPick;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xl),
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: IntrinsicHeight(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Spacer(),
                Text(
                  '01.',
                  style: AppTypography.mono(theme.textTheme.displayMedium)
                      ?.copyWith(color: AppColors.signalRed),
                ),
                const SizedBox(height: AppSpacing.md),
                Text('Delivery video.', style: theme.textTheme.headlineMedium),
                const SizedBox(height: AppSpacing.md),
                Text(
                  'Record or choose one clip of the delivery. You calibrate on a '
                  'frame from it, then the same clip is analysed.',
                  style: theme.textTheme.bodyLarge
                      ?.copyWith(color: scheme.onSurfaceVariant),
                ),
                const Spacer(),
                DrsButton(
                  label: 'RECORD VIDEO',
                  icon: Icons.videocam_outlined,
                  onPressed: () => onPick(ImageSource.camera),
                ),
                const SizedBox(height: AppSpacing.md),
                DrsButton(
                  label: 'CHOOSE FILE',
                  icon: Icons.folder_open,
                  style: DrsButtonStyle.secondary,
                  onPressed: () => onPick(ImageSource.gallery),
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
    'queued': 'Waiting for a worker',
    'starting': 'Loading the video',
    'decode': 'Reading frames from your clip',
    'calibration': 'Calibrating the pitch with your taps',
    'tracking': 'Finding the ball in every frame',
    'reconstruction': 'Reconstructing the 3D trajectory',
    'lbw': 'Running the LBW decision',
    'finalize': 'Wrapping up the report',
    'succeeded': 'Done',
    'failed': 'Failed',
  };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final p = (pct ?? 0).clamp(0, 100);
    final stageKey = (stage ?? 'working').toLowerCase();
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
              style: AppTypography.mono(theme.textTheme.displayLarge)
                  ?.copyWith(color: hasError ? scheme.error : AppColors.signalRed),
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              stageKey.toUpperCase(),
              style: theme.textTheme.labelMedium?.copyWith(
                color: scheme.onSurfaceVariant,
                letterSpacing: 1.4,
              ),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              help,
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: scheme.onSurface,
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            // Determinate bar when the backend has emitted a percent, animated
            // indeterminate bar otherwise — so the user always sees motion and
            // can tell the difference between "stuck at this percent" and
            // "still working but no measurable progress yet".
            SizedBox(
              width: 240,
              child: pct == null
                  ? LinearProgressIndicator(
                      color: AppColors.signalRed,
                      backgroundColor: scheme.surfaceContainerHigh,
                    )
                  : LinearProgressIndicator(
                      value: p / 100.0,
                      color: hasError ? scheme.error : AppColors.signalRed,
                      backgroundColor: scheme.surfaceContainerHigh,
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

class _ResultsView extends StatelessWidget {
  const _ResultsView({
    required this.videoPath,
    required this.result,
    required this.decision,
    required this.reason,
    required this.jobId,
    required this.onRestart,
  });
  final String videoPath;
  final AnalysisResult result;
  final String? decision;
  final String? reason;
  final String? jobId;
  final VoidCallback onRestart;

  Future<void> _open3D(BuildContext context) async {
    final id = jobId;
    if (id == null) return;
    try {
      final base = await AppSettings.getServerUrl();
      final token = await FirebaseAuth.instance.currentUser?.getIdToken();
      final url = (base.endsWith('/') ? base : '$base/') +
          'v1/jobs/$id/three-d' +
          (token == null ? '' : '?token=$token');
      if (kIsWeb) {
        openWebUrl(url);
      } else if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('3D view: $url')),
        );
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not open 3D view: $e')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SafeArea(
      child: Column(
        children: [
          Expanded(
            child: TrajectoryVideoView(
              videoPath: videoPath,
              result: result,
              decision: decision,
            ),
          ),
          Container(
            width: double.infinity,
            color: AppColors.inkBlack,
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.xl,
              AppSpacing.md,
              AppSpacing.xl,
              AppSpacing.lg,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (reason != null && reason!.isNotEmpty) ...[
                  Text(
                    reason!,
                    textAlign: TextAlign.center,
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: AppColors.bone),
                  ),
                  const SizedBox(height: AppSpacing.md),
                ],
                if (jobId != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                    child: DrsButton(
                      label: 'VIEW 3D HAWK-EYE',
                      icon: Icons.view_in_ar,
                      style: DrsButtonStyle.secondary,
                      onPressed: () => _open3D(context),
                    ),
                  ),
                DrsButton(
                  label: 'NEW ANALYSIS',
                  icon: Icons.refresh,
                  onPressed: onRestart,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
