import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';

import '../analysis/ball_track_models.dart';
import '../analysis/ball_tracker.dart';
import '../utils/format.dart';
import 'ball_seed_screen.dart';

class AnalysisScreen extends StatefulWidget {
  const AnalysisScreen({
    super.key,
    required this.videoPath,
    required this.start,
    required this.end,
  });

  final String videoPath;
  final Duration start;
  final Duration end;

  @override
  State<AnalysisScreen> createState() => _AnalysisScreenState();
}

class _AnalysisScreenState extends State<AnalysisScreen> {
  BallTrackResult? _result;
  String? _error;
  bool _running = false;
  Offset _seedPixel = const Offset(-1, -1);

  @override
  void initState() {
    super.initState();
    _chooseSeedThenRun();
  }

  Future<void> _chooseSeedThenRun() async {
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
    });
    try {
      // Ask the user for a single tap seed in the first frame of the segment.
      final seed = await Navigator.of(context).push<Offset?>(
        MaterialPageRoute(
          builder: (_) => BallSeedScreen(
            videoPath: widget.videoPath,
            timeMs: widget.start.inMilliseconds,
          ),
        ),
      );
      if (seed == null) {
        throw StateError('Ball selection cancelled');
      }
      _seedPixel = seed;

      final tracker = BallTracker();
      final req = BallTrackRequest(
        videoPath: widget.videoPath,
        startMs: widget.start.inMilliseconds,
        endMs: widget.end.inMilliseconds,
        sampleFps: 30,
        initialBallPixel: _seedPixel,
        searchRadiusPx: 160,
      );
      final res = await tracker.track(req);

      if (!mounted) return;
      setState(() {
        _result = res;
        _running = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _running = false;
      });
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
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text('Analysis error', style: theme.textTheme.titleLarge),
                        const SizedBox(height: 8),
                        Text(_error!),
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
                            Text(
                              'Next: we’ll add pitch calibration + LBW prediction using this track.',
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
