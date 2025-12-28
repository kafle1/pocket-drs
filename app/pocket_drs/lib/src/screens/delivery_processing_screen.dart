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

      while (mounted) {
        final status = await api.getJobStatus(jobId);
        _log('[DELIVERY] Poll: status=${status.status}, pct=${status.pct}, stage=${status.stage}');
        if (!mounted) return;
        setState(() {
          _progressPct = status.pct;
          _progressStage = status.stage ?? status.status;
          _progressError = status.errorMessage;
        });
        if (status.status == 'succeeded') break;
        if (status.status == 'failed') {
          throw StateError(status.errorMessage ?? 'Server analysis failed');
        }
        await Future.delayed(const Duration(milliseconds: 450));
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
        return _UploadIntro(onPick: _pickVideo);
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
        return _ProcessingView(
          jobId: _jobId,
          pct: _progressPct,
          stage: _progressStage,
          error: _progressError,
          onTryAgain: () => setState(() => _step = _Step.trim),
        );
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

class _UploadIntro extends StatelessWidget {
  const _UploadIntro({required this.onPick});
  final void Function(ImageSource) onPick;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 120,
              height: 120,
              decoration: BoxDecoration(
                color: theme.colorScheme.primaryContainer.withOpacity(0.5),
                shape: BoxShape.circle,
              ),
              child: Icon(
                Icons.video_camera_back_outlined,
                size: 48,
                color: theme.colorScheme.primary,
              ),
            ),
            const SizedBox(height: 32),
            Text(
              'Analyze Delivery',
              style: theme.textTheme.headlineMedium?.copyWith(
                fontWeight: FontWeight.bold,
                color: theme.colorScheme.onSurface,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 12),
            Text(
              'Record or upload a video of the delivery\nyou want to analyze.',
              style: theme.textTheme.bodyLarge?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
                height: 1.5,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 48),
            SizedBox(
              width: double.infinity,
              height: 56,
              child: FilledButton.icon(
                onPressed: () => onPick(ImageSource.camera),
                icon: const Icon(Icons.videocam_outlined),
                label: const Text('Record Video'),
              ),
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              height: 56,
              child: OutlinedButton.icon(
                onPressed: () => onPick(ImageSource.gallery),
                icon: const Icon(Icons.folder_open_outlined),
                label: const Text('Choose from Gallery'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ProcessingView extends StatelessWidget {
  const _ProcessingView({
    required this.jobId,
    required this.pct,
    required this.stage,
    required this.error,
    required this.onTryAgain,
  });

  final String? jobId;
  final int? pct;
  final String? stage;
  final String? error;
  final VoidCallback onTryAgain;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final stageText = switch (stage) {
      'queued' => 'Queued for analysis…',
      'downloading' => 'Processing video…',
      'processing' => 'Tracking ball path…',
      'analyzing' => 'Calculating trajectory…',
      _ => 'Working…',
    };

    final progress = ((pct ?? 0) / 100.0).clamp(0.0, 1.0);

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (error != null)
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: theme.colorScheme.errorContainer,
                  shape: BoxShape.circle,
                ),
                child: Icon(Icons.error_outline, size: 48, color: theme.colorScheme.error),
              )
            else
              SizedBox(
                width: 84,
                height: 84,
                child: CircularProgressIndicator(
                  value: pct == null ? null : progress,
                  strokeWidth: 6,
                  backgroundColor: theme.colorScheme.surfaceContainerHighest,
                ),
              ),
            const SizedBox(height: 32),
            Text(
              error != null ? 'Analysis Failed' : 'Analyzing Delivery',
              style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 12),
            Text(
              error ?? stageText,
              style: theme.textTheme.bodyLarge?.copyWith(
                color: error != null ? theme.colorScheme.error : theme.colorScheme.onSurfaceVariant,
              ),
              textAlign: TextAlign.center,
            ),
            if (jobId != null) ...[
              const SizedBox(height: 24),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                decoration: BoxDecoration(
                  color: theme.colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  'ID: ${jobId!.length > 8 ? jobId!.substring(0, 8) : jobId}…',
                  style: theme.textTheme.labelSmall?.copyWith(
                    fontFamily: 'monospace',
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ),
            ],
            if (error != null) ...[
              const SizedBox(height: 32),
              FilledButton.tonal(
                onPressed: onTryAgain,
                child: const Text('Try Again'),
              ),
            ],
          ],
        ),
      ),
    );
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
  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_update);
  }

  @override
  void dispose() {
    widget.controller.removeListener(_update);
    super.dispose();
  }

  void _update() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final ctl = widget.controller;
    final ready = widget.start != null && widget.end != null;

    return Column(
      children: [
        Expanded(
          child: Container(
            color: Colors.black,
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
            boxShadow: [
              BoxShadow(
                color: Colors.black.withOpacity(0.1),
                blurRadius: 10,
                offset: const Offset(0, -5),
              ),
            ],
          ),
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Trim Video',
                          style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'Select the delivery start and end points',
                          style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                        ),
                      ],
                    ),
                  ),
                  IconButton.filledTonal(
                    onPressed: () {
                      ctl.value.isPlaying ? ctl.pause() : ctl.play();
                    },
                    icon: Icon(ctl.value.isPlaying ? Icons.pause : Icons.play_arrow),
                    iconSize: 32,
                  ),
                ],
              ),
              const SizedBox(height: 24),
              VideoProgressIndicator(
                ctl,
                allowScrubbing: true,
                colors: VideoProgressColors(
                  playedColor: theme.colorScheme.primary,
                  bufferedColor: theme.colorScheme.surfaceContainerHighest,
                  backgroundColor: theme.colorScheme.surfaceContainer,
                ),
                padding: const EdgeInsets.symmetric(vertical: 8),
              ),
              const SizedBox(height: 24),
              Row(
                children: [
                  Expanded(
                    child: _TrimButton(
                      label: 'Set Start',
                      time: widget.start,
                      onTap: widget.onSetStart,
                      fmt: widget.fmt,
                      isActive: true,
                    ),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: _TrimButton(
                      label: 'Set End',
                      time: widget.end,
                      onTap: widget.onSetEnd,
                      fmt: widget.fmt,
                      isActive: widget.start != null,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                height: 56,
                child: FilledButton(
                  onPressed: ready ? widget.onProcess : null,
                  child: const Text('Analyze Delivery'),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _TrimButton extends StatelessWidget {
  const _TrimButton({
    required this.label,
    required this.time,
    required this.onTap,
    required this.fmt,
    required this.isActive,
  });

  final String label;
  final Duration? time;
  final VoidCallback onTap;
  final String Function(Duration) fmt;
  final bool isActive;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final hasValue = time != null;

    return OutlinedButton(
      onPressed: isActive ? onTap : null,
      style: OutlinedButton.styleFrom(
        padding: const EdgeInsets.symmetric(vertical: 16),
        backgroundColor: hasValue ? theme.colorScheme.primaryContainer.withOpacity(0.3) : null,
        side: BorderSide(
          color: hasValue ? theme.colorScheme.primary : theme.colorScheme.outline,
          width: hasValue ? 2 : 1,
        ),
      ),
      child: Column(
        children: [
          Text(label, style: TextStyle(
            color: isActive ? theme.colorScheme.primary : theme.colorScheme.outline,
            fontWeight: FontWeight.w600,
          )),
          if (hasValue) ...[
            const SizedBox(height: 4),
            Text(fmt(time!), style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurface,
              fontWeight: FontWeight.bold,
            )),
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

    final badgeColor = switch (decision) {
      'out' => theme.colorScheme.error,
      'not_out' => const Color(0xFF10B981), // Emerald
      'umpires_call' => const Color(0xFFF59E0B), // Amber
      _ => theme.colorScheme.outline,
    };

    return Stack(
      children: [
        Pitch3DViewer(
          trajectoryPoints: trajectory,
          showAnimation: true,
          bounceIndex: bounceIndex,
          impactIndex: impactIndex,
          decision: decision,
        ),
        Positioned(
          left: 16,
          right: 16,
          bottom: 32,
          child: Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: theme.colorScheme.surface.withOpacity(0.95),
              borderRadius: BorderRadius.circular(24),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.2),
                  blurRadius: 20,
                  offset: const Offset(0, 10),
                ),
              ],
              border: Border.all(
                color: theme.colorScheme.outlineVariant.withOpacity(0.5),
              ),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'DECISION',
                  style: theme.textTheme.labelSmall?.copyWith(
                    letterSpacing: 1.5,
                    fontWeight: FontWeight.bold,
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  decisionLabel,
                  style: theme.textTheme.displaySmall?.copyWith(
                    fontWeight: FontWeight.w900,
                    color: badgeColor,
                    letterSpacing: -0.5,
                  ),
                ),
                if (reason != null && reason!.trim().isNotEmpty) ...[
                  const SizedBox(height: 16),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: theme.colorScheme.surfaceContainerHighest.withOpacity(0.5),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      reason!,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: theme.colorScheme.onSurface,
                      ),
                      textAlign: TextAlign.center,
                    ),
                  ),
                ],
                const SizedBox(height: 24),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed: onReset,
                        style: OutlinedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 16),
                        ),
                        child: const Text('New Analysis'),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FilledButton(
                        onPressed: () => Navigator.pop(context),
                        style: FilledButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          backgroundColor: theme.colorScheme.primary,
                        ),
                        child: const Text('Done'),
                      ),
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
