import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../analysis/ball_track_models.dart';
import '../analysis/ball_tracker.dart';
import '../analysis/calibration_config.dart';
import '../api/pocket_drs_api.dart';
import '../utils/analysis_logger.dart';
import '../utils/app_settings.dart';
import '../utils/format.dart';
import '../utils/route_interactive.dart';
import 'ball_seed_screen.dart';
import 'lbw_review_screen.dart';

class AnalysisScreen extends StatefulWidget {
  const AnalysisScreen({
    super.key,
    required this.videoPath,
    required this.start,
    required this.end,
    required this.calibration,
  });

  final String videoPath;
  final Duration start;
  final Duration end;
  final CalibrationConfig calibration;

  @override
  State<AnalysisScreen> createState() => _AnalysisScreenState();
}

class _AnalysisScreenState extends State<AnalysisScreen> {
  BallTrackResult? _result;
  String? _error;
  bool _running = false;
  Offset _seedPixel = const Offset(-1, -1);
  String? _logPath;

  int? _progressPct;
  String? _progressStage;
  String? _jobId;

  @override
  void initState() {
    super.initState();
    // Don't navigate during the route push transition.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _chooseSeedThenRun();
    });
  }

  Future<void> _chooseSeedThenRun() async {
    if (_running) return;
    if (kIsWeb) {
      setState(() {
        _running = false;
        _error = 'Analysis is not supported on Web/Desktop. Run on Android/iOS.';
      });
      return;
    }

    setState(() {
      _running = true;
      _error = null;
      _result = null;
      _logPath = null;
      _progressPct = null;
      _progressStage = null;
      _jobId = null;
    });
    try {
      final logger = AnalysisLogger.instance;
      await logger.clear();
      final path = await logger.logPath();
      if (mounted) {
        setState(() => _logPath = path);
      }
      await logger.log('analysis start video=${widget.videoPath} start=${widget.start.inMilliseconds} end=${widget.end.inMilliseconds}');

      if (!mounted) return;

      // Ensure we're not trying to push while this route is still animating in.
      await waitForRouteInteractive(context);
      if (!mounted) return;

      // Ask the user for a single tap seed in the first frame of the segment.
      final startMs = widget.start.inMilliseconds;
      final endMs = widget.end.inMilliseconds;
      final initialMs = (startMs + 200).clamp(startMs, endMs);

      final seed = await Navigator.of(context).push<Offset?>(
        MaterialPageRoute(
          builder: (_) => BallSeedScreen(
            videoPath: widget.videoPath,
            startMs: startMs,
            endMs: endMs,
            initialMs: initialMs,
          ),
        ),
      );
      if (!mounted) return;
      if (seed == null) {
        throw StateError('Ball selection cancelled');
      }
      _seedPixel = seed;

      final res = await _runBackendOrLocal(seed: _seedPixel);
      await logger.log('analysis complete points=${res.points.length}');

      if (!mounted) return;
      setState(() {
        _result = res;
        _running = false;
      });
    } catch (e) {
      await AnalysisLogger.instance.log('analysis error: $e');
      if (!mounted) return;
      String msg = e.toString();
      if (msg.contains('Ball selection cancelled')) {
        // User cancelled, not an error - just go back
        if (mounted) Navigator.of(context).pop();
        return;
      }
      msg = msg.replaceAll(RegExp(r'^\\w+Error: '), '');
      if (msg.contains('decode first frame')) {
        msg = 'Could not read the video file. The file may be corrupted or in an unsupported format.';
      }
      setState(() {
        _error = msg;
        _running = false;
      });
    }
  }

  Future<BallTrackResult> _runBackendOrLocal({required Offset seed}) async {
    final useBackend = await AppSettings.getUseBackend();
    final url = await AppSettings.getServerUrl();

    if (useBackend && url.trim().isNotEmpty) {
      try {
        return await _runBackend(url: url.trim(), seed: seed);
      } catch (e) {
        await AnalysisLogger.instance.log('backend analysis failed; falling back to on-device: $e');
        if (mounted) {
          setState(() {
            _progressStage = null;
            _progressPct = null;
            _jobId = null;
          });
        }
        // Fall back to local analysis to avoid leaving the user stuck.
        return _runLocal(seed: seed);
      }
    }

    return _runLocal(seed: seed);
  }

  Future<BallTrackResult> _runLocal({required Offset seed}) async {
    final tracker = BallTracker();
    final req = BallTrackRequest(
      videoPath: widget.videoPath,
      startMs: widget.start.inMilliseconds,
      endMs: widget.end.inMilliseconds,
      sampleFps: 30,
      initialBallPixel: seed,
      searchRadiusPx: 160,
    );
    return tracker.track(req);
  }

  Future<BallTrackResult> _runBackend({required String url, required Offset seed}) async {
    final api = PocketDrsApi(baseUrl: url);
    try {
      if (mounted) {
        setState(() {
          _progressStage = 'upload';
          _progressPct = 0;
        });
      }

      final pitchCal = widget.calibration.pitchCalibration;
      final pitchCorners = pitchCal?.imagePoints;
      final hasPitchTaps = pitchCorners != null && pitchCorners.length == 4;

      List<Map<String, Object?>>? pitchCornersPx;
      Map<String, Object?>? pitchDims;
      if (hasPitchTaps) {
        final corners = pitchCorners;
        pitchCornersPx = corners
            .map((p) => <String, Object?>{'x': p.dx, 'y': p.dy})
            .toList(growable: false);
        pitchDims = <String, Object?>{
          'length': widget.calibration.pitchLengthM,
          'width': widget.calibration.pitchWidthM,
        };
      }

      final requestJson = <String, Object?>{
        'client': <String, Object?>{
          'platform': 'flutter',
          'app_version': '1.0.0',
        },
        'video': <String, Object?>{
          'source': 'import',
          'rotation_deg': 0,
        },
        'segment': <String, Object?>{
          'start_ms': widget.start.inMilliseconds,
          'end_ms': widget.end.inMilliseconds,
        },
        'calibration': <String, Object?>{
          'mode': hasPitchTaps ? 'taps' : 'none',
          'pitch_corners_px': pitchCornersPx,
          'pitch_dimensions_m': pitchDims,
        },
        'tracking': <String, Object?>{
          'mode': 'seeded',
          'seed_px': <String, Object?>{'x': seed.dx, 'y': seed.dy},
          'max_frames': 180,
          'sample_fps': 30,
        },
        'overrides': <String, Object?>{
          'bounce_index': null,
          'impact_index': null,
          'full_toss': false,
        },
      };

      final jobId = await api.createJob(
        videoFile: File(widget.videoPath),
        requestJson: requestJson,
      );

      if (mounted) {
        setState(() {
          _jobId = jobId;
          _progressStage = 'queued';
          _progressPct = 0;
        });
      }

      final deadline = DateTime.now().add(const Duration(minutes: 2));
      while (DateTime.now().isBefore(deadline)) {
        final status = await api.getJobStatus(jobId);
        if (mounted) {
          setState(() {
            _progressStage = status.stage ?? status.status;
            _progressPct = status.pct;
          });
        }

        if (status.status == 'succeeded') break;
        if (status.status == 'failed') {
          throw StateError(status.errorMessage ?? 'Server job failed');
        }

        await Future<void>.delayed(const Duration(milliseconds: 300));
      }

      final result = await api.getJobResult(jobId);

      final imageSize = result['image_size'];
      int width = 0;
      int height = 0;
      if (imageSize is Map) {
        final w = imageSize['width'];
        final h = imageSize['height'];
        if (w is num) width = w.round();
        if (h is num) height = h.round();
      }

      final track = result['track'];
      if (track is! Map) throw const FormatException('Server result missing track');
      final points = track['points'];
      if (points is! List) throw const FormatException('Server result missing track.points');

      final out = <BallTrackPoint>[];
      for (final v in points) {
        if (v is! Map) continue;
        final t = v['t_ms'];
        final x = v['x_px'];
        final y = v['y_px'];
        final c = v['confidence'];
        if (t is num && x is num && y is num && c is num) {
          out.add(
            BallTrackPoint(
              t: t.round(),
              p: Offset(x.toDouble(), y.toDouble()),
              confidence: c.toDouble(),
            ),
          );
        }
      }

      if (out.isEmpty) {
        throw StateError('Server returned zero track points');
      }

      // If server didn't provide dimensions, infer from points to keep UI usable.
      if (width <= 0 || height <= 0) {
        final maxX = out.map((p) => p.p.dx).fold<double>(0, (a, b) => a > b ? a : b);
        final maxY = out.map((p) => p.p.dy).fold<double>(0, (a, b) => a > b ? a : b);
        width = maxX.ceil().clamp(1, 100000);
        height = maxY.ceil().clamp(1, 100000);
      }

      return BallTrackResult(points: out, width: width, height: height);
    } finally {
      api.close();
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final title = 'Tracking (${formatDuration(widget.start)} → ${formatDuration(widget.end)})';

    return Scaffold(
      appBar: AppBar(
        title: Text(title),
        actions: [
          IconButton(
            tooltip: 'Re-run',
            onPressed: _running ? null : _chooseSeedThenRun,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        child: _running
            ? Center(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const CircularProgressIndicator(),
                      const SizedBox(height: 12),
                      if (_progressStage != null || _progressPct != null)
                        Text(
                          '${_progressStage ?? 'Working…'}${_progressPct == null ? '' : ' ($_progressPct%)'}',
                          textAlign: TextAlign.center,
                        ),
                      if (_jobId != null) ...[
                        const SizedBox(height: 4),
                        Text(
                          'Job: $_jobId',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              )
            : _error != null
                ? Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text('Analysis error', style: theme.textTheme.titleLarge),
                        const SizedBox(height: 8),
                        Text(_error!),
                        const SizedBox(height: 8),
                        _CalibrationSummary(calibration: widget.calibration),
                        if (_logPath != null) ...[
                          const SizedBox(height: 8),
                          Text('Log saved to: $_logPath'),
                        ],
                        const SizedBox(height: 16),
                        FilledButton(
                          onPressed: _chooseSeedThenRun,
                          child: const Text('Try again'),
                        ),
                      ],
                    ),
                  )
                : _result == null
                    ? const SizedBox.shrink()
                    : Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Expanded(
                              child: DecoratedBox(
                                decoration: BoxDecoration(
                                  color: theme.colorScheme.surfaceContainer,
                                  borderRadius: BorderRadius.circular(12),
                                ),
                                child: CustomPaint(
                                  painter: _TrajectoryPainter(result: _result!),
                                  child: const SizedBox.expand(),
                                ),
                              ),
                            ),
                            const SizedBox(height: 12),
                            Text(
                              'Tracked points: ${_result!.points.length}',
                              style: theme.textTheme.titleMedium,
                            ),
                            const SizedBox(height: 4),
                            _CalibrationSummary(calibration: widget.calibration),
                            const SizedBox(height: 8),
                            if (widget.calibration.pitchCalibration != null) ...[
                              FilledButton.icon(
                                onPressed: () async {
                                  final res = _result;
                                  if (res == null || !mounted) return;
                                  await Navigator.of(context).push(
                                    MaterialPageRoute(
                                      builder: (_) => LbwReviewScreen(
                                        track: res,
                                        calibration: widget.calibration,
                                      ),
                                    ),
                                  );
                                },
                                icon: const Icon(Icons.sports_cricket),
                                label: const Text('LBW assist (prototype)'),
                              ),
                              const SizedBox(height: 8),
                              Text(
                                'You can tweak the pitch/bounce point and see a top‑down prediction at the stumps (x=0).',
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: theme.colorScheme.onSurfaceVariant,
                                ),
                              ),
                            ] else
                              Text(
                                'Tip: add pitch calibration (4 corner taps) to enable LBW assist.',
                                style: theme.textTheme.bodyMedium?.copyWith(
                                  color: theme.colorScheme.onSurfaceVariant,
                                ),
                              ),
                          ],
                        ),
                      ),
      ),
    );
  }
}

class _CalibrationSummary extends StatelessWidget {
  const _CalibrationSummary({required this.calibration});

  final CalibrationConfig calibration;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Text(
      'Calibration: pitch ${calibration.pitchLengthM.toStringAsFixed(2)}m · '
      'stumps ${calibration.stumpHeightM.toStringAsFixed(3)}m · '
      'camera h ${calibration.cameraHeightM.toStringAsFixed(2)}m · '
      'dist ${calibration.cameraDistanceToStumpsM.toStringAsFixed(2)}m · '
      'offset ${calibration.cameraLateralOffsetM.toStringAsFixed(2)}m',
      style: theme.textTheme.bodySmall?.copyWith(
        color: theme.colorScheme.onSurfaceVariant,
      ),
    );
  }
}

class _TrajectoryPainter extends CustomPainter {
  _TrajectoryPainter({required this.result});

  final BallTrackResult result;

  @override
  void paint(Canvas canvas, Size size) {
    if (result.points.isEmpty) return;
    final sx = size.width / result.width;
    final sy = size.height / result.height;
    final scale = sx < sy ? sx : sy;
    final dx = (size.width - result.width * scale) / 2;
    final dy = (size.height - result.height * scale) / 2;

    Offset map(Offset p) => Offset(dx + p.dx * scale, dy + p.dy * scale);

    final path = Path();
    for (var i = 0; i < result.points.length; i++) {
      final pt = map(result.points[i].p);
      if (i == 0) {
        path.moveTo(pt.dx, pt.dy);
      } else {
        path.lineTo(pt.dx, pt.dy);
      }
    }

    final paintLine = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3
      ..color = const Color(0xFF2563EB);
    canvas.drawPath(path, paintLine);

    final paintDot = Paint()
      ..style = PaintingStyle.fill
      ..color = const Color(0xFFEF4444);
    canvas.drawCircle(map(result.points.first.p), 6, paintDot);
    canvas.drawCircle(map(result.points.last.p), 6, paintDot);
  }

  @override
  bool shouldRepaint(covariant _TrajectoryPainter oldDelegate) {
    return oldDelegate.result.points.length != result.points.length;
  }
}
