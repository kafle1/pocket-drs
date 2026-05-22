import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../api/analysis_result.dart';
import '../theme/app_colors.dart';
import '../utils/video_controller_factory.dart';

/// Broadcast-style result view: the source clip with the Hawk-Eye overlay drawn
/// over it — red ball path through the bounce, the blue on-stumps corridor on
/// the ground, gold stumps, and Speed / Spin / Swing metric cards. Modelled on
/// the FullTrack-AI presentation: the live scene is dimmed so the telemetry
/// reads cleanly, and the real flight stops at the bat/pad impact while the
/// dashed continuation is the predicted path to the stumps.
class TrajectoryVideoView extends StatefulWidget {
  const TrajectoryVideoView({
    super.key,
    required this.videoPath,
    required this.result,
    this.decision,
  });

  final String videoPath;
  final AnalysisResult result;
  final String? decision; // 'out' | 'not_out' | 'umpires_call'

  @override
  State<TrajectoryVideoView> createState() => _TrajectoryVideoViewState();
}

class _TrajectoryVideoViewState extends State<TrajectoryVideoView> {
  VideoPlayerController? _controller;
  String? _error;

  int _windowStartMs = 0;
  int _windowEndMs = 1 << 30;

  @override
  void initState() {
    super.initState();
    _initVideo();
  }

  Future<void> _initVideo() async {
    final controller = createVideoPlayerController(widget.videoPath);
    try {
      await controller.initialize();
      _computeWindow(controller.value.duration.inMilliseconds);
      await controller.setVolume(0);
      await controller.setLooping(false);
      await controller.seekTo(Duration(milliseconds: _windowStartMs));
      controller.addListener(_onTick);
      await controller.play();
      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() => _controller = controller);
    } catch (_) {
      await controller.dispose();
      if (mounted) setState(() => _error = 'Could not play the video.');
    }
  }

  void _computeWindow(int durationMs) {
    final path = widget.result.overlay?.path;
    if (path == null || path.isEmpty) {
      _windowStartMs = 0;
      _windowEndMs = durationMs > 0 ? durationMs : (1 << 30);
      return;
    }
    final flight = path.where((p) => !p.predicted);
    final firstT = (flight.isEmpty ? path.first : flight.first).tMs;
    final lastT = (flight.isEmpty ? path.last : flight.last).tMs;
    _windowStartMs = (firstT - 250).clamp(0, durationMs <= 0 ? firstT : durationMs);
    _windowEndMs = durationMs <= 0 ? lastT + 600 : (lastT + 600).clamp(0, durationMs);
    if (_windowEndMs <= _windowStartMs) _windowEndMs = durationMs > 0 ? durationMs : lastT + 600;
  }

  void _onTick() {
    final c = _controller;
    if (c == null || !c.value.isInitialized) return;
    if (c.value.position.inMilliseconds >= _windowEndMs) {
      c.seekTo(Duration(milliseconds: _windowStartMs));
    }
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _controller?.removeListener(_onTick);
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) {
      return Center(child: Text(_error!, style: const TextStyle(color: AppColors.bone)));
    }
    final c = _controller;
    if (c == null || !c.value.isInitialized) {
      return const Center(child: CircularProgressIndicator(color: AppColors.signalRed));
    }

    final overlay = widget.result.overlay;
    final metrics = widget.result.metrics;
    final imgW = widget.result.imageWidth.toDouble();
    final imgH = widget.result.imageHeight.toDouble();
    final aspect = (imgW > 0 && imgH > 0) ? imgW / imgH : c.value.aspectRatio;
    final nowMs = c.value.position.inMilliseconds;

    return Center(
      child: AspectRatio(
        aspectRatio: aspect,
        child: Stack(
          fit: StackFit.expand,
          children: [
            FittedBox(
              fit: BoxFit.cover,
              clipBehavior: Clip.hardEdge,
              child: SizedBox(
                width: imgW > 0 ? imgW : c.value.size.width,
                height: imgH > 0 ? imgH : c.value.size.height,
                child: VideoPlayer(c),
              ),
            ),
            const ColoredBox(color: Color(0x4D000000)),
            if (overlay != null && imgW > 0 && imgH > 0)
              CustomPaint(
                painter: _OverlayPainter(
                  overlay: overlay,
                  imageWidth: imgW,
                  imageHeight: imgH,
                  nowMs: nowMs,
                ),
              ),
            if (metrics != null)
              Positioned(
                top: 14,
                left: 12,
                child: _MetricStack(metrics: metrics, decision: widget.decision),
              ),
            Positioned(
              right: 8,
              bottom: 8,
              child: _ReplayButton(
                playing: c.value.isPlaying,
                onTap: () {
                  if (c.value.isPlaying) {
                    c.pause();
                  } else {
                    c.seekTo(Duration(milliseconds: _windowStartMs));
                    c.play();
                  }
                  setState(() {});
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _OverlayPainter extends CustomPainter {
  _OverlayPainter({
    required this.overlay,
    required this.imageWidth,
    required this.imageHeight,
    required this.nowMs,
  });

  final TrajectoryOverlay overlay;
  final double imageWidth;
  final double imageHeight;
  final int nowMs;

  static const _gold = Color(0xFFEAC785);
  static const _corridorFill = Color(0x553C74E0);
  static const _corridorEdge = Color(0xAA6E9BF0);

  @override
  void paint(Canvas canvas, Size size) {
    final sx = size.width / imageWidth;
    final sy = size.height / imageHeight;
    Offset map(Offset p) => Offset(p.dx * sx, p.dy * sy);

    // Pitch corridor on the ground (drawn first, under everything).
    if (overlay.corridor.length >= 3) {
      final path = Path()..moveTo(map(overlay.corridor.first).dx, map(overlay.corridor.first).dy);
      for (final p in overlay.corridor.skip(1)) {
        final o = map(p);
        path.lineTo(o.dx, o.dy);
      }
      path.close();
      canvas.drawPath(path, Paint()..color = _corridorFill);
      canvas.drawPath(path, Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.0
        ..color = _corridorEdge);
    }

    // Stumps: bowler end faint, striker (batsman) end prominent gold.
    if (overlay.bowlerStumps != null) {
      _drawStumps(canvas, map(overlay.bowlerStumps!.base), map(overlay.bowlerStumps!.top),
          color: _gold.withValues(alpha: 0.45), width: 2.5, prominent: false);
    }
    if (overlay.strikerStumps != null) {
      _drawStumps(canvas, map(overlay.strikerStumps!.base), map(overlay.strikerStumps!.top),
          color: _gold, width: 5.0, prominent: true);
    }

    // Ball path — one continuous red line (release → bounce → impact), with the
    // predicted continuation to the stumps dashed. Matches the FullTrack red arc.
    final flight = [for (final p in overlay.path) if (!p.predicted) map(p.px)];
    final predicted = <Offset>[
      if (overlay.impact != null) map(overlay.impact!.px),
      for (final p in overlay.path) if (p.predicted) map(p.px),
    ];
    _drawDashed(canvas, predicted, AppColors.signalRed.withValues(alpha: 0.8), 3.0);
    _drawPolyline(canvas, flight, AppColors.signalRed, 4.5, glow: true);

    if (overlay.bounce != null) {
      _drawPitchMarker(canvas, map(overlay.bounce!.px));
    }
    if (overlay.impact != null) {
      _drawDot(canvas, map(overlay.impact!.px), _gold, 5.0);
    }

    final ball = _ballAt(overlay.path, map, nowMs);
    if (ball != null) {
      canvas.drawCircle(ball, 11.0, Paint()..color = AppColors.bone.withValues(alpha: 0.25));
      canvas.drawCircle(ball, 6.0, Paint()..color = AppColors.bone);
    }
  }

  Offset? _ballAt(List<OverlayPoint> path, Offset Function(Offset) map, int t) {
    final flight = [for (final p in path) if (!p.predicted) p];
    if (flight.length < 2) return null;
    if (t <= flight.first.tMs) return null;
    if (t >= flight.last.tMs) return map(flight.last.px);
    for (var i = 1; i < flight.length; i++) {
      final a = flight[i - 1];
      final b = flight[i];
      if (t >= a.tMs && t <= b.tMs) {
        final span = b.tMs - a.tMs;
        final f = span <= 0 ? 0.0 : (t - a.tMs) / span;
        return Offset.lerp(map(a.px), map(b.px), f);
      }
    }
    return null;
  }

  void _drawStumps(Canvas canvas, Offset base, Offset top,
      {required Color color, required double width, required bool prominent}) {
    if (prominent) {
      canvas.drawLine(base, top, Paint()
        ..color = color.withValues(alpha: 0.30)
        ..strokeCap = StrokeCap.round
        ..strokeWidth = width + 7.0);
    }
    canvas.drawLine(base, top, Paint()
      ..color = color
      ..strokeCap = StrokeCap.round
      ..strokeWidth = width);
    canvas.drawCircle(top, prominent ? 4.0 : 2.5, Paint()..color = color);
  }

  void _drawPolyline(Canvas canvas, List<Offset> pts, Color color, double width, {bool glow = false}) {
    if (pts.length < 2) return;
    final path = Path()..moveTo(pts.first.dx, pts.first.dy);
    for (var i = 1; i < pts.length; i++) {
      path.lineTo(pts[i].dx, pts[i].dy);
    }
    if (glow) {
      canvas.drawPath(path, Paint()
        ..style = PaintingStyle.stroke
        ..strokeJoin = StrokeJoin.round
        ..strokeCap = StrokeCap.round
        ..color = color.withValues(alpha: 0.25)
        ..strokeWidth = width + 7.0);
    }
    canvas.drawPath(path, Paint()
      ..style = PaintingStyle.stroke
      ..strokeJoin = StrokeJoin.round
      ..strokeCap = StrokeCap.round
      ..color = color
      ..strokeWidth = width);
  }

  void _drawDashed(Canvas canvas, List<Offset> pts, Color color, double width) {
    if (pts.length < 2) return;
    const dash = 12.0;
    const gap = 8.0;
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeWidth = width;
    for (var i = 1; i < pts.length; i++) {
      var a = pts[i - 1];
      final b = pts[i];
      final seg = b - a;
      final len = seg.distance;
      if (len == 0) continue;
      final dir = seg / len;
      var drawn = 0.0;
      var on = true;
      while (drawn < len) {
        final step = (on ? dash : gap).clamp(0.0, len - drawn);
        if (on) canvas.drawLine(a, a + dir * step, paint);
        a = a + dir * step;
        drawn += step;
        on = !on;
      }
    }
  }

  void _drawPitchMarker(Canvas canvas, Offset c) {
    canvas.drawCircle(c, 10.0, Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.5
      ..color = AppColors.signalRed);
    canvas.drawCircle(c, 4.0, Paint()..color = AppColors.signalRed);
    _label(canvas, c + const Offset(13, -8), 'PITCH', AppColors.signalRed);
  }

  void _drawDot(Canvas canvas, Offset c, Color color, double r) {
    canvas.drawCircle(c, r + 3, Paint()..color = color.withValues(alpha: 0.25));
    canvas.drawCircle(c, r, Paint()..color = color);
  }

  void _label(Canvas canvas, Offset at, String text, Color color) {
    final tp = TextPainter(
      text: TextSpan(
        text: text,
        style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 1.0),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, at);
  }

  @override
  bool shouldRepaint(_OverlayPainter old) =>
      old.nowMs != nowMs || old.overlay != overlay || old.imageWidth != imageWidth;
}

class _MetricStack extends StatelessWidget {
  const _MetricStack({required this.metrics, required this.decision});
  final DeliveryMetrics metrics;
  final String? decision;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _MetricCard(
          icon: Icons.speed_rounded,
          label: 'Speed',
          value: metrics.speedMph.toStringAsFixed(0),
          unit: 'mph',
        ),
        const SizedBox(height: 8),
        _MetricCard(
          icon: Icons.rotate_right_rounded,
          label: 'Spin',
          value: metrics.spinDeg.toStringAsFixed(1),
          unit: '°',
        ),
        const SizedBox(height: 8),
        _MetricCard(
          icon: Icons.air_rounded,
          label: 'Swing',
          value: metrics.swingSf.toStringAsFixed(1),
          unit: 'sf',
        ),
        if (decision != null) ...[
          const SizedBox(height: 10),
          _DecisionChip(decision: decision!),
        ],
      ],
    );
  }
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({
    required this.icon,
    required this.label,
    required this.value,
    required this.unit,
  });
  final IconData icon;
  final String label;
  final String value;
  final String unit;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 124,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: const Color(0xCC101012),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0x22FFFFFF)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                label.toUpperCase(),
                style: const TextStyle(
                  color: AppColors.ash,
                  fontSize: 10,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 1.2,
                ),
              ),
              Icon(icon, size: 15, color: AppColors.ash),
            ],
          ),
          const SizedBox(height: 3),
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Text(
                value,
                style: const TextStyle(
                  color: AppColors.bone,
                  fontSize: 22,
                  fontWeight: FontWeight.w800,
                  height: 1.0,
                ),
              ),
              const SizedBox(width: 4),
              Text(
                unit,
                style: const TextStyle(
                  color: AppColors.bone,
                  fontSize: 12,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _DecisionChip extends StatelessWidget {
  const _DecisionChip({required this.decision});
  final String decision;

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (decision) {
      'out' => ('OUT', AppColors.signalRed),
      'not_out' => ('NOT OUT', AppColors.pitchGreen),
      'umpires_call' => ("UMPIRE'S CALL", AppColors.caution),
      _ => (decision.toUpperCase(), AppColors.bone),
    };
    return Container(
      width: 124,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: const Color(0xCC101012),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color, width: 1.4),
      ),
      child: Text(
        label,
        textAlign: TextAlign.center,
        style: TextStyle(color: color, fontSize: 14, fontWeight: FontWeight.w800, letterSpacing: 1.4),
      ),
    );
  }
}

class _ReplayButton extends StatelessWidget {
  const _ReplayButton({required this.playing, required this.onTap});
  final bool playing;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: const Color(0xCC0A0A0B),
      shape: const CircleBorder(),
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(10),
          child: Icon(playing ? Icons.pause : Icons.replay, color: AppColors.bone, size: 22),
        ),
      ),
    );
  }
}
