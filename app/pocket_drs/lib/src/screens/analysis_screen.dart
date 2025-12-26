import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';

import '../analysis/ball_track_models.dart';
import '../analysis/calibration_config.dart';
import '../api/analysis_result.dart';
import '../api/pocket_drs_api.dart';
import '../utils/analysis_logger.dart';
import '../utils/app_settings.dart';
import '../utils/format.dart';
import '../utils/route_interactive.dart';
import '../models/video_source.dart';
import 'ball_seed_screen.dart';
import 'lbw_review_screen.dart';

class AnalysisScreen extends StatefulWidget {
  const AnalysisScreen({
    super.key,
    required this.videoFile,
    required this.start,
    required this.end,
    required this.calibration,
    required this.videoSource,
  });

  final XFile videoFile;
  final Duration start;
  final Duration end;
  final CalibrationConfig calibration;
  final VideoSource videoSource;

  @override
  State<AnalysisScreen> createState() => _AnalysisScreenState();
}

class _AnalysisScreenState extends State<AnalysisScreen> {
  AnalysisResult? _result;
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

  String _userMessageFor(Object e) {
    if (e is TimeoutException) {
      return 'Timed out while talking to the server.\n\n'
          'Make sure your phone and server are on the same Wi‑Fi and the server is running.';
    }
    if (e is http.ClientException) {
      return 'Could not reach the server.\n\n'
          'Check the Server URL in Settings and confirm the server is running.';
    }
    if (e is FormatException) {
      return 'Server returned an unexpected response.\n\n'
          'Check server logs and ensure client/server versions match.';
    }

    final msg = e.toString().replaceAll(RegExp(r'^\w+Error: '), '');
    return msg.isEmpty ? 'Unknown error' : msg;
  }

  Future<void> _chooseSeedThenRun() async {
    if (_running) return;

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
      await logger.log('analysis start video=${widget.videoFile.path} start=${widget.start.inMilliseconds} end=${widget.end.inMilliseconds}');

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
            videoPath: widget.videoFile.path,
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

      final res = await _runBackend(seed: _seedPixel);
      await logger.log('analysis complete points=${res.track.points.length}');

      if (!mounted) return;
      setState(() {
        _result = res;
        _running = false;
      });
    } catch (e, st) {
      await AnalysisLogger.instance.logException(e, st, context: 'analysis');
      if (!mounted) return;
      final raw = e.toString();
      if (raw.contains('Ball selection cancelled')) {
        // User cancelled, not an error - just go back
        if (mounted) Navigator.of(context).pop();
        return;
      }
      setState(() {
        _error = _userMessageFor(e);
        _running = false;
      });
    }
  }

  Future<AnalysisResult> _runBackend({required Offset seed}) async {
    final url = (await AppSettings.getServerUrl()).trim();
    final effectiveUrl = url.isNotEmpty ? url : AppSettings.defaultServerUrl();

    await AnalysisLogger.instance.logAndPrint(
      'backend start baseUrl=$effectiveUrl source=${widget.videoSource.wireValue} video=${widget.videoFile.path} segment=${widget.start.inMilliseconds}-${widget.end.inMilliseconds}',
    );

    final api = PocketDrsApi(baseUrl: effectiveUrl);
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
          'source': widget.videoSource.wireValue,
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
        videoBytes: await widget.videoFile.readAsBytes(),
        videoFilename: widget.videoFile.name,
        requestJson: requestJson,
      );

      await AnalysisLogger.instance.logAndPrint('backend createJob ok jobId=$jobId');

      if (mounted) {
        setState(() {
          _jobId = jobId;
          _progressStage = 'queued';
          _progressPct = 0;
        });
      }

      JobStatus? last;
      final deadline = DateTime.now().add(const Duration(minutes: 2));
      while (DateTime.now().isBefore(deadline)) {
        final status = await api.getJobStatus(jobId);
        last = status;

        await AnalysisLogger.instance.log(
          'backend poll jobId=$jobId status=${status.status} pct=${status.pct ?? '-'} stage=${status.stage ?? '-'} err=${status.errorMessage ?? '-'}',
        );
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

      if (last == null) {
        throw TimeoutException('No status received from server');
      }
      if (last.status != 'succeeded') {
        throw TimeoutException('Server job did not finish in time (last=${last.status}, stage=${last.stage ?? '-'})');
      }

      final res = await api.getJobResult(jobId);
      await AnalysisLogger.instance.logAndPrint(
        'backend result ok jobId=$jobId points=${res.track.points.length} warnings=${res.warnings.length}',
      );
      return res;
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
                                  painter: _TrajectoryPainter(result: _result!.track),
                                  child: const SizedBox.expand(),
                                ),
                              ),
                            ),
                            const SizedBox(height: 12),
                            Text(
                              'Tracked points: ${_result!.track.points.length}',
                              style: theme.textTheme.titleMedium,
                            ),
                            if (_result!.warnings.isNotEmpty) ...[
                              const SizedBox(height: 4),
                              Text(
                                'Warnings: ${_result!.warnings.join(' · ')}',
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: theme.colorScheme.onSurfaceVariant,
                                ),
                              ),
                            ],
                            const SizedBox(height: 4),
                            _CalibrationSummary(calibration: widget.calibration),
                            const SizedBox(height: 8),
                            if (_result!.lbw != null && _result!.pitchPlane.isNotEmpty) ...[
                              FilledButton.icon(
                                onPressed: () async {
                                  final res = _result;
                                  if (res == null || !mounted) return;
                                  await Navigator.of(context).push(
                                    MaterialPageRoute(
                                      builder: (_) => LbwReviewScreen(
                                        analysis: res,
                                        calibration: widget.calibration,
                                      ),
                                    ),
                                  );
                                },
                                icon: const Icon(Icons.sports_cricket),
                                label: const Text('LBW review'),
                              ),
                              const SizedBox(height: 8),
                              Text(
                                'Uses backend pipeline outputs (events + pitch plane + LBW decision).',
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: theme.colorScheme.onSurfaceVariant,
                                ),
                              ),
                            ] else
                              Text(
                                'Tip: add pitch calibration (4 corner taps) to enable LBW review.',
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
