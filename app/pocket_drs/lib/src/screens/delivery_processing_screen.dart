import 'dart:async';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:video_player/video_player.dart';

import '../api/analysis_result.dart';
import '../api/pocket_drs_api.dart';
import '../utils/app_settings.dart';
import '../utils/pitch_store.dart';
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

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  void _log(String message) {
    if (kDebugMode) {
      debugPrint(message);
    }
  }

  Future<void> _pickVideo(ImageSource source) async {
    try {
      final video = await _picker.pickVideo(source: source);
      if (video == null || !mounted) return;
      final controller = VideoPlayerController.file(File(video.path));
      await controller.initialize();
      if (mounted) {
        setState(() {
          _video = video;
          _controller = controller;
          _step = _Step.trim;
        });
      }
    } catch (e) {
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

    // Capture any BuildContext-derived values BEFORE awaits to avoid lint issues.
    final platformName = Theme.of(context).platform.name;

    // Validate pitch calibration before processing.
    final pitchBefore = await _pitchStore.loadById(widget.pitchId);
    if (!mounted) return;
    if (pitchBefore?.calibration?.pitchCalibration == null) {
      _showCalibrationError();
      return;
    }

    setState(() => _step = _Step.process);

    String? serverUrl;
    try {
      serverUrl = await AppSettings.getServerUrl();
      _log('[DELIVERY] Using server URL: $serverUrl');
      final api = PocketDrsApi(baseUrl: serverUrl);

      final pitch = await _pitchStore.loadById(widget.pitchId);
      final calibration = pitch?.calibration;
      final pitchCal = calibration?.pitchCalibration;
      if (pitch == null || calibration == null || pitchCal == null) {
        throw StateError('Pitch is not calibrated');
      }

      final bytes = await _video!.readAsBytes();

      // Send normalized pitch corners when available so the server can adapt
      // to the delivery video resolution.
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
        'client': <String, Object?>{
          'platform': platformName,
          'app_version': 'dev',
        },
        'segment': <String, Object?>{
          'start_ms': _start!.inMilliseconds,
          'end_ms': _end!.inMilliseconds,
        },
        'calibration': <String, Object?>{
          'mode': 'taps',
          'pitch_corners_norm': cornersNorm,
          if (pitchCal.stumpPointsNorm != null && pitchCal.stumpPointsNorm!.length == 4)
            'stump_bases_norm': <Map<String, Object?>>[
              <String, Object?>{'x': pitchCal.stumpPointsNorm![0].dx, 'y': pitchCal.stumpPointsNorm![0].dy},
              <String, Object?>{'x': pitchCal.stumpPointsNorm![2].dx, 'y': pitchCal.stumpPointsNorm![2].dy},
            ],
          'pitch_dimensions_m': <String, Object?>{
            'length': calibration.pitchLengthM,
            'width': calibration.pitchWidthM,
          },
        },
        'tracking': <String, Object?>{
          'mode': 'auto',
          'max_frames': 180,
          'sample_fps': 60,
        },
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
      while (mounted && pollCount < maxPolls) {
        pollCount++;
        
        try {
          final status = await api.getJobStatus(jobId);
          _log('[DELIVERY] Poll #$pollCount: status=${status.status}, pct=${status.pct}, stage=${status.stage}');
          
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
          
          // Progressive delay: faster checks at start, slower later
          final delay = pollCount < 10 ? 500 : (pollCount < 30 ? 800 : 1200);
          await Future.delayed(Duration(milliseconds: delay));
        } catch (e) {
          _log('[DELIVERY] Poll error: $e');
          // Continue polling even on transient errors
          await Future.delayed(const Duration(milliseconds: 1000));
        }
      }
      
      if (pollCount >= maxPolls) {
        throw StateError('Analysis timed out after $pollCount attempts');
      }

      final analysis = await api.getJobResult(jobId);
      _log('[DELIVERY] Result fetched: ${analysis.pitchPlane.length} points');
      final payload = _buildHawkEyePayload(analysis);

      if (!mounted) return;
      setState(() {
        _trajectory3d = payload.points;
        _bounceIndex = payload.bounceIndex;
        _impactIndex = payload.impactIndex;
        _decision = payload.decision;
        _decisionReason = payload.reason;
        _step = _Step.results;
      });
    } catch (e, stack) {
      _log('[DELIVERY] Error: $e');
      _log('[DELIVERY] Stack: $stack');
      if (mounted) {
        setState(() => _step = _Step.trim);
        final msg = e is StateError
            ? e.message
            : (e.toString().contains('SocketException')
                ? 'Cannot reach server${serverUrl != null ? ' at $serverUrl' : ''}'
                : 'Analysis failed: $e');
        _showError(msg);
      }
    }
  }

  _HawkEyePayload _buildHawkEyePayload(AnalysisResult analysis) {
    final ptsM = analysis.pitchPlane;
    if (ptsM.isEmpty) {
      throw StateError('Server did not return pitch-plane points. Recalibrate the pitch and try again.');
    }

    final bounceIdx = analysis.events?.bounceIndex ?? (ptsM.length ~/ 2);
    final impactIdx = analysis.events?.impactIndex ?? (ptsM.length - 1);

    final safeBounce = bounceIdx.clamp(0, ptsM.length - 1);
    final safeImpact = impactIdx.clamp(0, ptsM.length - 1);

    final points = <Map<String, double>>[];

    // Synthetic height curve for a "3D" feel.
    final preBounceDen = safeBounce == 0 ? 1.0 : safeBounce.toDouble();
    for (var i = 0; i < ptsM.length; i++) {
      final p = ptsM[i].worldM;
      final x = p.dx;
      final y = p.dy;
      double z;
      if (i <= safeBounce) {
        final t = i / preBounceDen;
        z = (1.8 * (1.0 - (t - 0.55).abs() * 1.6)).clamp(0.0, 1.8);
      } else {
        z = 0.0;
      }
      points.add({'x': x, 'y': y, 'z': z});
    }

    // Predicted path from impact -> stumps (x=0), using server-provided y_at_stumps if available.
    final lbw = analysis.lbw;
    if (lbw != null && safeImpact < ptsM.length) {
      final impact = ptsM[safeImpact].worldM;
      final yAtStumps = lbw.yAtStumpsM;

      const n = 14;
      for (var i = 1; i <= n; i++) {
        final t = i / n;
        final x = impact.dx + (0.0 - impact.dx) * t;
        final y = impact.dy + (yAtStumps - impact.dy) * t;
        points.add({'x': x, 'y': y, 'z': 0.0});
      }
    }

    final decision = switch (analysis.lbw?.decision) {
      LbwDecisionKey.out => 'out',
      LbwDecisionKey.notOut => 'not_out',
      LbwDecisionKey.umpiresCall => 'umpires_call',
      _ => null,
    };

    return _HawkEyePayload(
      points: points,
      bounceIndex: safeBounce,
      impactIndex: safeImpact,
      decision: decision,
      reason: analysis.lbw?.reason,
    );
  }

  void _reset() {
    _controller?.dispose();
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
    });
  }

  void _goBack() {
    switch (_step) {
      case _Step.trim:
        _controller?.dispose();
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
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), behavior: SnackBarBehavior.floating),
    );
  }

  void _showCalibrationError() {
    if (!mounted) return;
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Pitch Not Calibrated'),
        content: const Text(
          'This pitch has not been calibrated yet. Please go back and calibrate '
          'the pitch first by marking the pitch corners and stumps.',
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.of(context).pop(); // Close dialog
              Navigator.of(context).pop(); // Go back to pitch screen
            },
            child: const Text('Go Back'),
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
    final showAppBar = _step != _Step.results;
    return Scaffold(
      backgroundColor: _step == _Step.results ? Colors.black : null,
      appBar: showAppBar
          ? AppBar(
              backgroundColor: Colors.transparent,
              elevation: 0,
              leading: IconButton(icon: const Icon(Icons.arrow_back), onPressed: _goBack),
              title: Text(widget.pitchName),
              bottom: _step != _Step.process
                  ? PreferredSize(
                      preferredSize: const Size.fromHeight(40),
                      child: _StepBar(current: _step.index),
                    )
                  : null,
            )
          : null,
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
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
  const _StepBar({required this.current});
  final int current;
  static const _labels = ['Upload', 'Trim', 'Process', 'Results'];

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 8),
      child: Row(
        children: List.generate(_labels.length - 1, (i) {
          final done = i < current;
          final active = i == current;
          return Expanded(
            child: Row(
              children: [
                _Dot(done: done, active: active, index: i),
                Expanded(
                  child: Container(
                    height: 2,
                    color: done ? theme.colorScheme.primary : theme.colorScheme.outlineVariant.withValues(alpha: 0.3),
                  ),
                ),
              ],
            ),
          );
        })..add(Expanded(child: Row(children: [_Dot(done: false, active: current == 3, index: 3)]))),
      ),
    );
  }
}

class _Dot extends StatelessWidget {
  const _Dot({required this.done, required this.active, required this.index});
  final bool done;
  final bool active;
  final int index;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      width: 24,
      height: 24,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: done ? theme.colorScheme.primary : active ? theme.colorScheme.primaryContainer : Colors.transparent,
        border: Border.all(
          color: done || active ? theme.colorScheme.primary : theme.colorScheme.outlineVariant,
          width: 2,
        ),
      ),
      child: Center(
        child: done
            ? Icon(Icons.check, size: 12, color: theme.colorScheme.onPrimary)
            : Text('${index + 1}', style: theme.textTheme.labelSmall?.copyWith(
                color: active ? theme.colorScheme.primary : theme.colorScheme.onSurfaceVariant,
                fontWeight: FontWeight.w600,
              )),
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
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 80,
              height: 80,
              decoration: BoxDecoration(
                color: theme.colorScheme.primaryContainer,
                shape: BoxShape.circle,
              ),
              child: Icon(Icons.video_file_outlined, size: 36, color: theme.colorScheme.primary),
            ),
            const SizedBox(height: 24),
            Text('Delivery Video', style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
            Text(
              'Record or upload a video of\nthe delivery you want to analyze',
              style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 40),
            SizedBox(
              width: 200,
              child: FilledButton.icon(
                onPressed: () => onPick(ImageSource.camera),
                icon: const Icon(Icons.videocam),
                label: const Text('Record Video'),
                style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 16)),
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: 200,
              child: OutlinedButton.icon(
                onPressed: () => onPick(ImageSource.gallery),
                icon: const Icon(Icons.folder_open),
                label: const Text('Choose File'),
                style: OutlinedButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 16)),
              ),
            ),
          ],
        ),
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
    final ctl = widget.controller;
    final ready = widget.start != null && widget.end != null;

    final dur = ctl.value.duration;
    final pos = ctl.value.position;
    final maxMs = dur.inMilliseconds <= 0 ? 1.0 : dur.inMilliseconds.toDouble();
    final sliderValueMs = (_scrubbing ? (_scrubValueMs ?? pos.inMilliseconds.toDouble()) : pos.inMilliseconds.toDouble())
      .clamp(0.0, maxMs)
      .toDouble();
    final shownPos = Duration(milliseconds: sliderValueMs.toInt());

    return Column(
      children: [
        Expanded(
          child: Container(
            color: theme.colorScheme.surfaceContainerLowest,
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
            color: theme.colorScheme.surface,
            border: Border(top: BorderSide(color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3))),
          ),
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: [
                  // Timeline
                  Row(
                    children: [
                      Text(widget.fmt(shownPos), style: theme.textTheme.labelSmall),
                      const SizedBox(width: 8),
                      Expanded(
                        child: SliderTheme(
                          data: SliderTheme.of(context).copyWith(
                            trackHeight: 4,
                            thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 8),
                          ),
                          child: Slider(
                            value: sliderValueMs,
                            max: maxMs,
                            onChangeStart: (_) {
                              if (ctl.value.isPlaying) {
                                ctl.pause();
                              }
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
                      ),
                      const SizedBox(width: 8),
                      Text(widget.fmt(dur), style: theme.textTheme.labelSmall),
                    ],
                  ),
                  const SizedBox(height: 8),
                  // Playback controls
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      IconButton(
                        icon: const Icon(Icons.replay_5),
                        onPressed: () => ctl.seekTo(ctl.value.position - const Duration(seconds: 5)),
                      ),
                      const SizedBox(width: 8),
                      FloatingActionButton.small(
                        onPressed: () => ctl.value.isPlaying ? ctl.pause() : ctl.play(),
                        child: Icon(ctl.value.isPlaying ? Icons.pause : Icons.play_arrow),
                      ),
                      const SizedBox(width: 8),
                      IconButton(
                        icon: const Icon(Icons.forward_5),
                        onPressed: () => ctl.seekTo(ctl.value.position + const Duration(seconds: 5)),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  // Selection display
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                    decoration: BoxDecoration(
                      color: theme.colorScheme.surfaceContainer,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(
                          widget.start != null ? widget.fmt(widget.start!) : '--:--',
                          style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
                        ),
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 12),
                          child: Icon(Icons.arrow_forward, size: 16, color: theme.colorScheme.onSurfaceVariant),
                        ),
                        Text(
                          widget.end != null ? widget.fmt(widget.end!) : '--:--',
                          style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  // Mark buttons
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton(
                          onPressed: widget.onSetStart,
                          child: const Text('Mark Start'),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: OutlinedButton(
                          onPressed: widget.start != null ? widget.onSetEnd : null,
                          child: const Text('Mark End'),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: ready ? widget.onProcess : null,
                      child: const Text('Analyze Delivery'),
                    ),
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

class _ProcessingView extends StatelessWidget {
  const _ProcessingView({required this.jobId, required this.pct, required this.stage, required this.error});

  final String? jobId;
  final int? pct;
  final String? stage;
  final String? error;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final p = (pct ?? 0).clamp(0, 100);
    final stageText = stage ?? 'working';
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(
            width: 72,
            height: 72,
            child: Stack(
              fit: StackFit.expand,
              children: [
                CircularProgressIndicator(
                  strokeWidth: 3,
                  value: p <= 0 ? null : p / 100.0,
                ),
                Center(
                  child: Text(
                    '$p%',
                    style: theme.textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 32),
          Text('Analyzing delivery…', style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Text(
            error == null ? stageText : 'Error: $error',
            style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),
          if (jobId != null) ...[
            const SizedBox(height: 8),
            Text(
              'Job: $jobId',
              style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
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
    required this.onReset,
  });

  final List<Map<String, double>> trajectory;
  final int? bounceIndex;
  final int? impactIndex;
  final String? decision;
  final String? reason;
  final VoidCallback onReset;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    final decisionLabel = switch (decision) {
      'out' => 'OUT',
      'not_out' => 'NOT OUT',
      'umpires_call' => "UMPIRE'S CALL",
      _ => '—',
    };

    final badgeBg = switch (decision) {
      'out' => theme.colorScheme.errorContainer,
      'not_out' => theme.colorScheme.tertiaryContainer,
      'umpires_call' => theme.colorScheme.primaryContainer,
      _ => theme.colorScheme.surfaceContainerHighest,
    };

    final badgeFg = switch (decision) {
      'out' => theme.colorScheme.onErrorContainer,
      'not_out' => theme.colorScheme.onTertiaryContainer,
      'umpires_call' => theme.colorScheme.onPrimaryContainer,
      _ => theme.colorScheme.onSurfaceVariant,
    };

    return Column(
      children: [
        Expanded(
          child: Pitch3DViewer(
            trajectoryPoints: trajectory,
            showAnimation: true,
            bounceIndex: bounceIndex,
            impactIndex: impactIndex,
            decision: decision,
          ),
        ),
        Container(
          padding: const EdgeInsets.fromLTRB(24, 24, 24, 32),
          decoration: BoxDecoration(
            color: theme.colorScheme.surface,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
          ),
          child: SafeArea(
            top: false,
            child: Column(
              children: [
                Text('Decision', style: theme.textTheme.titleSmall?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 40, vertical: 16),
                  decoration: BoxDecoration(
                    color: badgeBg,
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Text(
                    decisionLabel,
                    style: theme.textTheme.headlineMedium?.copyWith(
                      fontWeight: FontWeight.bold,
                      color: badgeFg,
                    ),
                  ),
                ),
                if (reason != null && reason!.trim().isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text(
                    reason!,
                    style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    textAlign: TextAlign.center,
                  ),
                ],
                const SizedBox(height: 24),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(onPressed: onReset, child: const Text('New Analysis')),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FilledButton(onPressed: () => Navigator.pop(context), child: const Text('Done')),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
