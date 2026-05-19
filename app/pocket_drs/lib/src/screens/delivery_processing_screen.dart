import 'dart:async';
import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:image_picker/image_picker.dart';
import 'package:video_player/video_player.dart';

import '../api/analysis_result.dart';
import '../api/pocket_drs_api.dart';
import '../analysis/pitch_pose.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../utils/app_logger.dart';
import '../utils/app_settings.dart';
import '../utils/native_video_resources.dart';
import '../utils/pitch_store.dart';
import '../utils/video_controller_factory.dart';
import '../widgets/decision_badge.dart';
import '../widgets/drs_button.dart';
import '../widgets/pitch_3d_viewer.dart';

enum _Step { upload, trim, process, results }

class DeliveryProcessingScreen extends StatefulWidget {
  const DeliveryProcessingScreen({
    super.key,
    required this.pitchId,
    required this.pitchName,
  });

  final String pitchId;
  final String pitchName;

  @override
  State<DeliveryProcessingScreen> createState() => _DeliveryProcessingScreenState();
}

class _DeliveryProcessingScreenState extends State<DeliveryProcessingScreen> {
  final _picker = ImagePicker();
  final _pitchStore = PitchStore();

  _Step _step = _Step.upload;
  XFile? _video;
  VideoPlayerController? _controller;
  Duration? _start;
  Duration? _end;

  String? _jobId;
  int? _progressPct;
  String? _progressStage;
  String? _progressError;

  List<Map<String, double>>? _trajectory3d;
  int? _bounceIndex;
  int? _impactIndex;
  String? _decision;
  String? _decisionReason;
  PitchPose? _pitchPose;

  @override
  void dispose() {
    unawaited(_releaseController());
    super.dispose();
  }

  void _log(String message) => AppLogger.instance.log(message);

  Future<void> _releaseController() async {
    final controller = _controller;
    if (controller == null) return;
    _controller = null;
    await controller.pause();
    await controller.dispose();
    await coolDownNativeVideoResources();
  }

  Future<void> _pickVideo(ImageSource source) async {
    VideoPlayerController? controller;
    try {
      await _releaseController();
      final video = await _picker.pickVideo(source: source);
      if (video == null || !mounted) return;
      controller = createVideoPlayerController(video.path);
      await runWithNativeVideoResources(() async {
        await coolDownNativeVideoResources(delay: const Duration(milliseconds: 350));
        await controller!.initialize();
      });
      await controller.setVolume(0.0);
      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() {
        _video = video;
        _controller = controller;
        _start = null;
        _end = null;
        _step = _Step.trim;
      });
    } catch (_) {
      if (controller != null && !identical(controller, _controller)) {
        await controller.dispose();
      }
      _showError('Failed to load video');
    }
  }

  void _setStart() {
    if (_controller == null) return;
    setState(() => _start = _controller!.value.position);
  }

  void _setEnd() {
    if (_controller == null || _start == null) return;
    final pos = _controller!.value.position;
    if (pos <= _start!) {
      _showError('End must be after start');
      return;
    }
    setState(() => _end = pos);
  }

  Future<void> _process() async {
    if (_video == null || _start == null || _end == null) return;

    final platformName = Theme.of(context).platform.name;

    try {
      final pitchBefore = await _pitchStore.loadById(widget.pitchId);
      if (!mounted) return;
      if (pitchBefore?.calibration?.pitchCalibration == null) {
        _showCalibrationError();
        return;
      }
    } catch (_) {
      if (!mounted) return;
      _showError('Please sign in again');
      return;
    }

    await _releaseController();
    setState(() => _step = _Step.process);

    try {
      final serverUrl = await AppSettings.getServerUrl();
      _log('[DELIVERY] Using server URL: $serverUrl');

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

      final pitch = await _pitchStore.loadById(widget.pitchId);
      final calibration = pitch?.calibration;
      final pitchCal = calibration?.pitchCalibration;
      if (pitch == null || calibration == null || pitchCal == null) {
        throw StateError('Pitch is not calibrated');
      }

      final pitchPose = PitchPoseEstimator.fromCalibration(pitchCal);
      final bytes = await _video!.readAsBytes();

      List<Map<String, Object?>> cornersNorm;
      if (pitchCal.imagePointsNorm != null && pitchCal.imagePointsNorm!.length == 4) {
        cornersNorm = pitchCal.imagePointsNorm!
            .map((p) => <String, Object?>{'x': p.dx, 'y': p.dy})
            .toList(growable: false);
      } else if (pitchCal.imageSizePx != null && pitchCal.imagePoints.length == 4) {
        final w = pitchCal.imageSizePx!.width;
        final h = pitchCal.imageSizePx!.height;
        cornersNorm = pitchCal.imagePoints
            .map((p) => <String, Object?>{'x': p.dx / w, 'y': p.dy / h})
            .toList(growable: false);
      } else {
        throw StateError('Invalid pitch calibration');
      }

      final requestJson = <String, Object?>{
        'client': <String, Object?>{'platform': platformName, 'app_version': 'dev'},
        'segment': <String, Object?>{
          'start_ms': _start!.inMilliseconds,
          'end_ms': _end!.inMilliseconds,
        },
        'calibration': <String, Object?>{
          'mode': 'taps',
          'pitch_id': widget.pitchId,
          'pitch_corners_norm': cornersNorm,
          if (pitchCal.stumpPointsNorm != null && pitchCal.stumpPointsNorm!.length == 4)
            'stump_bases_norm': <Map<String, Object?>>[
              {'x': pitchCal.stumpPointsNorm![0].dx, 'y': pitchCal.stumpPointsNorm![0].dy},
              {'x': pitchCal.stumpPointsNorm![2].dx, 'y': pitchCal.stumpPointsNorm![2].dy},
            ],
          'pitch_dimensions_m': <String, Object?>{
            'length': calibration.pitchLengthM,
            'width': calibration.pitchWidthM,
          },
        },
        'tracking': <String, Object?>{'mode': 'auto', 'max_frames': 180, 'sample_fps': 60},
        'overrides': <String, Object?>{},
      };

      final jobId = await api.createJob(
        videoBytes: bytes,
        videoFilename: _video!.name,
        requestJson: requestJson,
      );
      _log('[DELIVERY] Job created: $jobId');

      if (!mounted) return;
      setState(() {
        _jobId = jobId;
        _progressPct = 0;
        _progressStage = 'queued';
        _progressError = null;
      });

      int pollCount = 0;
      const maxPolls = 240;
      const maxTransientErrors = 8;

      String? lastStatus;
      int? lastPct;
      String? lastStage;
      int transientPollErrors = 0;
      while (mounted && pollCount < maxPolls) {
        pollCount++;

        final JobStatus status;
        try {
          status = await api.getJobStatus(jobId);
        } catch (e) {
          if (e is StateError) rethrow;
          transientPollErrors++;
          if (transientPollErrors <= 3) {
            _log('[DELIVERY] Poll error (transient $transientPollErrors): $e');
          }
          if (transientPollErrors >= maxTransientErrors) {
            throw StateError('Lost connection to server while analysing');
          }
          await Future.delayed(const Duration(milliseconds: 1000));
          continue;
        }

        final changed = status.status != lastStatus || status.pct != lastPct || status.stage != lastStage;
        if (changed || pollCount == 1 || (pollCount % 20 == 0)) {
          _log('[DELIVERY] Poll #$pollCount: status=${status.status}, pct=${status.pct}, stage=${status.stage}');
          lastStatus = status.status;
          lastPct = status.pct;
          lastStage = status.stage;
        }

        if (!mounted) return;
        setState(() {
          _progressPct = status.pct;
          _progressStage = status.stage ?? status.status;
          _progressError = status.errorMessage;
        });

        if (status.status == 'succeeded') {
          _log('[DELIVERY] Job succeeded after $pollCount polls');
          break;
        }
        if (status.status == 'failed') {
          throw StateError(status.errorMessage ?? 'Server analysis failed');
        }

        final delay = pollCount < 10 ? 500 : (pollCount < 30 ? 800 : 1200);
        await Future.delayed(Duration(milliseconds: delay));
      }

      if (!mounted) return;
      if (pollCount >= maxPolls) {
        throw StateError('Analysis timed out after $pollCount attempts');
      }

      final analysis = await api.getJobResult(jobId);
      _log('[DELIVERY] Result fetched: ${analysis.worldTrajectory.points.length} 3D points');
      final payload = _buildHawkEyePayload(analysis);

      if (!mounted) return;
      setState(() {
        _trajectory3d = payload.points;
        _bounceIndex = payload.bounceIndex;
        _impactIndex = payload.impactIndex;
        _decision = payload.decision;
        _decisionReason = payload.reason;
        _pitchPose = pitchPose;
        _step = _Step.results;
      });
    } catch (e, stack) {
      _log('[DELIVERY] Error: $e');
      _log('[DELIVERY] Stack: $stack');
      if (mounted) {
        setState(() => _step = _Step.trim);
        final msg = e is ApiException ? e.message : 'Analysis failed: $e';
        _showError(msg);
      }
    }
  }

  _HawkEyePayload _buildHawkEyePayload(AnalysisResult analysis) {
    final world = analysis.worldTrajectory;
    if (!world.hasTrajectory) {
      throw StateError(
        'Server returned no 3D trajectory. The ball may not be detectable in this video, '
        'or the pitch calibration may be inaccurate. Try a clearer video or recalibrate.',
      );
    }

    final points = <Map<String, double>>[
      for (final p in world.points) p.toViewerJson(),
    ];

    var bounceIdx = -1;
    var impactIdx = -1;
    final events = analysis.events;
    if (events?.bounce != null) {
      bounceIdx = _indexOfNearestT(world.points, events!.bounce!.tMs);
    }
    if (events?.impact != null) {
      impactIdx = _indexOfNearestT(world.points, events!.impact!.tMs);
    }
    if (bounceIdx < 0) bounceIdx = (points.length / 2).floor();
    if (impactIdx < 0) impactIdx = points.length - 1;

    for (final p in world.predictedToStumps) {
      points.add(p.toViewerJson());
    }

    final decision = switch (analysis.lbw?.decision) {
      LbwDecisionKey.out => 'out',
      LbwDecisionKey.notOut => 'not_out',
      LbwDecisionKey.umpiresCall => 'umpires_call',
      _ => null,
    };

    return _HawkEyePayload(
      points: points,
      bounceIndex: bounceIdx,
      impactIndex: impactIdx,
      decision: decision,
      reason: analysis.lbw?.reason,
    );
  }

  int _indexOfNearestT(List<WorldPointM> pts, int tMs) {
    var best = -1;
    var bestDelta = 1 << 30;
    for (var i = 0; i < pts.length; i++) {
      final d = (pts[i].tMs - tMs).abs();
      if (d < bestDelta) {
        bestDelta = d;
        best = i;
      }
    }
    return best;
  }

  void _reset() {
    unawaited(_releaseController());
    setState(() {
      _step = _Step.upload;
      _video = null;
      _controller = null;
      _start = null;
      _end = null;
      _jobId = null;
      _progressPct = null;
      _progressStage = null;
      _progressError = null;
      _trajectory3d = null;
      _bounceIndex = null;
      _impactIndex = null;
      _decision = null;
      _decisionReason = null;
      _pitchPose = null;
    });
  }

  void _goBack() {
    switch (_step) {
      case _Step.trim:
        unawaited(_releaseController());
        setState(() {
          _step = _Step.upload;
          _video = null;
          _controller = null;
        });
      default:
        Navigator.pop(context);
    }
  }

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  void _showCalibrationError() {
    if (!mounted) return;
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Pitch not calibrated'),
        content: const Text(
          'Calibrate this pitch first by marking the pitch corners and stumps.',
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.of(context).pop();
              Navigator.of(context).pop();
            },
            child: const Text('BACK'),
          ),
        ],
      ),
    );
  }

  String _fmt(Duration d) {
    final m = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final showAppBar = _step != _Step.results;

    return Scaffold(
      backgroundColor: _step == _Step.results ? AppColors.inkBlack : scheme.surface,
      appBar: showAppBar
          ? PreferredSize(
              preferredSize: const Size.fromHeight(96),
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
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          IconButton(
                            onPressed: _goBack,
                            icon: const Icon(Icons.arrow_back, size: 20),
                          ),
                          const SizedBox(width: AppSpacing.xs),
                          Text(
                            'STEP ${(_step.index + 1).toString().padLeft(2, '0')} / 04',
                            style: theme.textTheme.labelSmall?.copyWith(
                              color: scheme.onSurfaceVariant,
                            ),
                          ),
                          const Spacer(),
                          Text(
                            widget.pitchName.toUpperCase(),
                            style: theme.textTheme.labelSmall?.copyWith(
                              color: scheme.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Padding(
                        padding: const EdgeInsets.only(left: AppSpacing.md),
                        child: Text(
                          switch (_step) {
                            _Step.upload => 'Upload',
                            _Step.trim => 'Trim',
                            _Step.process => 'Processing',
                            _Step.results => 'Results',
                          },
                          style: theme.textTheme.headlineSmall,
                        ),
                      ),
                      const SizedBox(height: AppSpacing.md),
                      _StepBar(current: _step.index, total: 4),
                    ],
                  ),
                ),
              ),
            )
          : null,
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_step == _Step.trim && _controller == null) {
      return _UploadStep(onPick: _pickVideo);
    }
    switch (_step) {
      case _Step.upload:
        return _UploadStep(onPick: _pickVideo);
      case _Step.trim:
        return _TrimStep(
          controller: _controller!,
          start: _start,
          end: _end,
          onSetStart: _setStart,
          onSetEnd: _setEnd,
          onProcess: _process,
          fmt: _fmt,
        );
      case _Step.process:
        return _ProcessingView(jobId: _jobId, pct: _progressPct, stage: _progressStage, error: _progressError);
      case _Step.results:
        return _ResultsView(
          trajectory: _trajectory3d!,
          bounceIndex: _bounceIndex,
          impactIndex: _impactIndex,
          decision: _decision,
          reason: _decisionReason,
          pose: _pitchPose,
          onReset: _reset,
        );
    }
  }
}

class _HawkEyePayload {
  const _HawkEyePayload({
    required this.points,
    required this.bounceIndex,
    required this.impactIndex,
    required this.decision,
    required this.reason,
  });

  final List<Map<String, double>> points;
  final int bounceIndex;
  final int impactIndex;
  final String? decision;
  final String? reason;
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
          final done = i <= current;
          return Expanded(
            child: Container(
              margin: EdgeInsets.only(right: i == total - 1 ? 0 : 2),
              color: done ? AppColors.signalRed : scheme.surfaceContainerHigh,
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
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Spacer(),
          Text(
            '01.',
            style: AppTypography.mono(theme.textTheme.displayMedium)?.copyWith(
              color: AppColors.signalRed,
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          Text('Delivery video.', style: theme.textTheme.headlineMedium),
          const SizedBox(height: AppSpacing.md),
          Text(
            'Record or choose a clip showing the delivery you want analysed.',
            style: theme.textTheme.bodyLarge?.copyWith(color: scheme.onSurfaceVariant),
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
    );
  }
}

class _TrimStep extends StatefulWidget {
  const _TrimStep({
    required this.controller,
    required this.start,
    required this.end,
    required this.onSetStart,
    required this.onSetEnd,
    required this.onProcess,
    required this.fmt,
  });

  final VideoPlayerController controller;
  final Duration? start;
  final Duration? end;
  final VoidCallback onSetStart;
  final VoidCallback onSetEnd;
  final VoidCallback onProcess;
  final String Function(Duration) fmt;

  @override
  State<_TrimStep> createState() => _TrimStepState();
}

class _TrimStepState extends State<_TrimStep> {
  Timer? _seekDebounce;
  bool _scrubbing = false;
  double? _scrubValueMs;

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_update);
  }

  @override
  void dispose() {
    _seekDebounce?.cancel();
    widget.controller.removeListener(_update);
    super.dispose();
  }

  void _scheduleSeekMs(int ms) {
    _seekDebounce?.cancel();
    _seekDebounce = Timer(const Duration(milliseconds: 200), () {
      if (!mounted) return;
      widget.controller.seekTo(Duration(milliseconds: ms));
    });
  }

  void _update() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final ctl = widget.controller;
    final ready = widget.start != null && widget.end != null;

    final dur = ctl.value.duration;
    final pos = ctl.value.position;
    final maxMs = dur.inMilliseconds <= 0 ? 1.0 : dur.inMilliseconds.toDouble();
    final sliderValueMs =
        (_scrubbing ? (_scrubValueMs ?? pos.inMilliseconds.toDouble()) : pos.inMilliseconds.toDouble())
            .clamp(0.0, maxMs)
            .toDouble();
    final shownPos = Duration(milliseconds: sliderValueMs.toInt());

    return Column(
      children: [
        Expanded(
          child: Container(
            color: AppColors.inkBlack,
            child: Center(
              child: AspectRatio(
                aspectRatio: ctl.value.aspectRatio,
                child: VideoPlayer(ctl),
              ),
            ),
          ),
        ),
        Container(
          decoration: BoxDecoration(
            color: scheme.surface,
            border: Border(top: BorderSide(color: scheme.outline, width: 1)),
          ),
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.xl,
                AppSpacing.lg,
                AppSpacing.xl,
                AppSpacing.lg,
              ),
              child: Column(
                children: [
                  Row(
                    children: [
                      Text(
                        widget.fmt(shownPos),
                        style: AppTypography.mono(theme.textTheme.labelMedium),
                      ),
                      Expanded(
                        child: Slider(
                          value: sliderValueMs,
                          max: maxMs,
                          onChangeStart: (_) {
                            if (ctl.value.isPlaying) ctl.pause();
                            setState(() {
                              _scrubbing = true;
                              _scrubValueMs = sliderValueMs;
                            });
                          },
                          onChanged: (v) {
                            setState(() => _scrubValueMs = v);
                            _scheduleSeekMs(v.toInt());
                          },
                          onChangeEnd: (v) {
                            _seekDebounce?.cancel();
                            ctl.seekTo(Duration(milliseconds: v.toInt()));
                            setState(() {
                              _scrubbing = false;
                              _scrubValueMs = null;
                            });
                          },
                        ),
                      ),
                      Text(
                        widget.fmt(dur),
                        style: AppTypography.mono(theme.textTheme.labelMedium)?.copyWith(
                          color: scheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      _MiniButton(
                        icon: Icons.replay_5,
                        onTap: () => ctl.seekTo(ctl.value.position - const Duration(seconds: 5)),
                      ),
                      const SizedBox(width: AppSpacing.md),
                      _MiniButton(
                        icon: ctl.value.isPlaying ? Icons.pause : Icons.play_arrow,
                        large: true,
                        onTap: () => ctl.value.isPlaying ? ctl.pause() : ctl.play(),
                      ),
                      const SizedBox(width: AppSpacing.md),
                      _MiniButton(
                        icon: Icons.forward_5,
                        onTap: () => ctl.seekTo(ctl.value.position + const Duration(seconds: 5)),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.lg,
                      vertical: AppSpacing.md,
                    ),
                    decoration: BoxDecoration(
                      border: Border.all(color: scheme.outline, width: 1),
                    ),
                    child: Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('IN', style: theme.textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant)),
                              const SizedBox(height: 2),
                              Text(
                                widget.start != null ? widget.fmt(widget.start!) : '--:--',
                                style: AppTypography.mono(theme.textTheme.titleLarge),
                              ),
                            ],
                          ),
                        ),
                        Container(width: 1, height: 36, color: scheme.outline),
                        const SizedBox(width: AppSpacing.lg),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('OUT', style: theme.textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant)),
                              const SizedBox(height: 2),
                              Text(
                                widget.end != null ? widget.fmt(widget.end!) : '--:--',
                                style: AppTypography.mono(theme.textTheme.titleLarge),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: AppSpacing.md),
                  Row(
                    children: [
                      Expanded(
                        child: DrsButton(
                          label: 'MARK IN',
                          style: DrsButtonStyle.secondary,
                          onPressed: widget.onSetStart,
                        ),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: DrsButton(
                          label: 'MARK OUT',
                          style: DrsButtonStyle.secondary,
                          onPressed: widget.start != null ? widget.onSetEnd : null,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.md),
                  DrsButton(
                    label: 'ANALYSE DELIVERY',
                    icon: Icons.bolt,
                    onPressed: ready ? widget.onProcess : null,
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _MiniButton extends StatelessWidget {
  const _MiniButton({required this.icon, required this.onTap, this.large = false});
  final IconData icon;
  final VoidCallback onTap;
  final bool large;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final size = large ? 48.0 : 40.0;
    return Material(
      color: large ? scheme.onSurface : Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.sm),
        side: BorderSide(color: scheme.outline, width: 1),
      ),
      child: InkWell(
        onTap: onTap,
        child: SizedBox(
          width: size,
          height: size,
          child: Icon(
            icon,
            size: large ? 24 : 18,
            color: large ? scheme.surface : scheme.onSurface,
          ),
        ),
      ),
    );
  }
}

class _ProcessingView extends StatelessWidget {
  const _ProcessingView({required this.jobId, required this.pct, required this.stage, required this.error});

  final String? jobId;
  final int? pct;
  final String? stage;
  final String? error;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final p = (pct ?? 0).clamp(0, 100);
    final stageText = stage ?? 'working';
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                p.toString().padLeft(2, '0'),
                style: AppTypography.mono(theme.textTheme.displayLarge)?.copyWith(
                  color: AppColors.signalRed,
                  height: 0.9,
                ),
              ),
              Padding(
                padding: const EdgeInsets.only(bottom: 12.0),
                child: Text(
                  '%',
                  style: AppTypography.mono(theme.textTheme.displaySmall)?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.lg),
          Text(
            'PROCESSING — ${stageText.toUpperCase()}',
            style: theme.textTheme.labelMedium?.copyWith(color: scheme.onSurfaceVariant),
          ),
          const SizedBox(height: AppSpacing.md),
          ClipRect(
            child: SizedBox(
              height: 4,
              child: LinearProgressIndicator(
                value: p <= 0 ? null : p / 100.0,
                backgroundColor: scheme.surfaceContainerHigh,
                color: AppColors.signalRed,
              ),
            ),
          ),
          if (jobId != null) ...[
            const SizedBox(height: AppSpacing.xl),
            Text(
              'JOB ${jobId!.split('-').first.toUpperCase()}',
              style: AppTypography.mono(theme.textTheme.labelSmall)?.copyWith(
                color: scheme.onSurfaceVariant,
              ),
            ),
          ],
          if (error != null) ...[
            const SizedBox(height: AppSpacing.lg),
            Text(
              error!,
              style: theme.textTheme.bodyMedium?.copyWith(color: scheme.error),
            ),
          ],
        ],
      ),
    );
  }
}

class _ResultsView extends StatelessWidget {
  const _ResultsView({
    required this.trajectory,
    required this.bounceIndex,
    required this.impactIndex,
    required this.decision,
    required this.reason,
    required this.pose,
    required this.onReset,
  });

  final List<Map<String, double>> trajectory;
  final int? bounceIndex;
  final int? impactIndex;
  final String? decision;
  final String? reason;
  final PitchPose? pose;
  final VoidCallback onReset;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final decisionKey = switch (decision) {
      'out' => LbwDecisionKey.out,
      'not_out' => LbwDecisionKey.notOut,
      'umpires_call' => LbwDecisionKey.umpiresCall,
      _ => null,
    };

    return Column(
      children: [
        Container(
          decoration: const BoxDecoration(
            color: AppColors.inkBlack,
            border: Border(bottom: BorderSide(color: AppColors.hairlineDark, width: 1)),
          ),
          child: SafeArea(
            bottom: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.lg,
                AppSpacing.md,
                AppSpacing.lg,
                AppSpacing.md,
              ),
              child: Row(
                children: [
                  IconButton(
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.arrow_back, color: AppColors.bone, size: 20),
                  ),
                  const SizedBox(width: AppSpacing.xs),
                  Text(
                    'DELIVERY RESULT',
                    style: theme.textTheme.labelSmall?.copyWith(color: AppColors.ash),
                  ),
                  const Spacer(),
                  Container(
                    width: 6,
                    height: 6,
                    decoration: const BoxDecoration(
                      color: AppColors.signalRed,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Text(
                    'LIVE',
                    style: theme.textTheme.labelSmall?.copyWith(color: AppColors.bone),
                  ),
                ],
              ),
            ),
          ),
        ),
        Expanded(
          child: Pitch3DViewer(
            trajectoryPoints: trajectory,
            showAnimation: true,
            bounceIndex: bounceIndex,
            impactIndex: impactIndex,
            decision: decision,
            pose: pose,
          ),
        ),
        Container(
          decoration: const BoxDecoration(
            color: AppColors.carbon,
            border: Border(top: BorderSide(color: AppColors.hairlineDark, width: 1)),
          ),
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.xl,
                AppSpacing.lg,
                AppSpacing.xl,
                AppSpacing.lg,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        'DECISION',
                        style: theme.textTheme.labelSmall?.copyWith(color: AppColors.ash),
                      ),
                      const SizedBox(width: AppSpacing.md),
                      DecisionBadge(decision: decisionKey, size: DecisionBadgeSize.large),
                    ],
                  ),
                  if (reason != null && reason!.trim().isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.md),
                    Text(
                      reason!,
                      style: theme.textTheme.bodyMedium?.copyWith(color: AppColors.ash),
                    ),
                  ],
                  const SizedBox(height: AppSpacing.lg),
                  Row(
                    children: [
                      Expanded(
                        child: DrsButton(
                          label: 'NEW',
                          style: DrsButtonStyle.secondary,
                          icon: Icons.refresh,
                          onPressed: onReset,
                        ),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: DrsButton(
                          label: 'DONE',
                          icon: Icons.check,
                          onPressed: () => Navigator.pop(context),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}
