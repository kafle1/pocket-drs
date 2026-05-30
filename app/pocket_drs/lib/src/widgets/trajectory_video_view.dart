import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../analysis/ball_track_models.dart';
import '../api/analysis_result.dart';
import '../theme/app_colors.dart';
import '../utils/app_settings.dart';
import '../utils/video_controller_factory.dart';

/// Broadcast-style result view: the source clip with the Hawk-Eye overlay drawn
/// over it — red ball path through the bounce, the blue on-stumps corridor on
/// the ground, gold stumps, and Speed / Spin / Swing metric cards. Modelled on
/// the FullTrack-AI presentation: the live scene is dimmed so the telemetry
/// reads cleanly, and the tracked flight continues, as one clean solid red
/// line, into the predicted path to the stumps.
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
  SpeedUnit _speedUnit = SpeedUnit.kmh;

  int _windowStartMs = 0;
  int _windowEndMs = 1 << 30;

  @override
  void initState() {
    super.initState();
    _initVideo();
    _loadSpeedUnit();
  }

  Future<void> _loadSpeedUnit() async {
    final u = await AppSettings.getSpeedUnit();
    if (mounted && u != _speedUnit) setState(() => _speedUnit = u);
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
    final lastT = path.last.tMs;
    _windowStartMs = (firstT - 250).clamp(
      0,
      durationMs <= 0 ? firstT : durationMs,
    );
    _windowEndMs = durationMs <= 0
        ? lastT + 600
        : (lastT + 600).clamp(0, durationMs);
    if (_windowEndMs <= _windowStartMs) {
      _windowEndMs = durationMs > 0 ? durationMs : lastT + 600;
    }
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
      return Center(
        child: Text(_error!, style: const TextStyle(color: AppColors.bone)),
      );
    }
    final c = _controller;
    if (c == null || !c.value.isInitialized) {
      return const Center(
        child: CircularProgressIndicator(color: AppColors.signalRed),
      );
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
            // Keep the scene bright like the broadcast render — only a faint
            // scrim so the overlay lines stay legible.
            const ColoredBox(color: Color(0x14000000)),
            if (overlay != null && imgW > 0 && imgH > 0)
              CustomPaint(
                painter: _OverlayPainter(
                  overlay: overlay,
                  track: widget.result.track.points,
                  imageWidth: imgW,
                  imageHeight: imgH,
                  nowMs: nowMs,
                ),
              ),
            if (metrics != null)
              Positioned(
                top: 14,
                left: 12,
                child: _MetricStack(
                  metrics: metrics,
                  decision: widget.decision,
                  speedUnit: _speedUnit,
                ),
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
    required this.track,
    required this.imageWidth,
    required this.imageHeight,
    required this.nowMs,
  });

  final TrajectoryOverlay overlay;

  /// Raw on-ball detections (pixel space) — the literal track the detector
  /// saw. Drawn as the flight line so it sits on the ball, instead of the
  /// fit projection which can drift near impact.
  final List<BallTrackPoint> track;
  final double imageWidth;
  final double imageHeight;
  final int nowMs;

  static const _blue = Color(0xFF3FA7FF); // calibrated pitch + corridor lines
  static const _yellow = Color(0xFFFFCF40); // stumps (pitch markings, not ball path)

  @override
  void paint(Canvas canvas, Size size) {
    final sx = size.width / imageWidth;
    final sy = size.height / imageHeight;
    Offset map(Offset p) => Offset(p.dx * sx, p.dy * sy);

    // Ball-path stroke, scaled to the display. The test3 reference renders the
    // path at 5 px on the full 1080-wide frame; matching that *relative* width
    // (5 * sx) keeps the line as thin and clean as the broadcast overlay on any
    // screen, instead of the previously fixed (and on phones much thicker) 4.5.
    final pathW = (5.0 * sx).clamp(1.5, 5.0);

    // ---- calibrated ground geometry (drawn under the ball path) ----
    // Full pitch outline — blue (proves the pitch calibration).
    _drawPolygon(canvas, [for (final p in overlay.pitchRect) map(p)], _blue, 2.2);
    // On-stumps corridor between the two wickets — translucent blue channel.
    final corridor = [for (final p in overlay.corridor) map(p)];
    if (corridor.length >= 4) {
      canvas.drawPath(
        Path()..addPolygon(corridor, true),
        Paint()
          ..color = _blue.withValues(alpha: 0.14)
          ..style = PaintingStyle.fill,
      );
      _drawPolygon(canvas, corridor, _blue, 1.6);
    }
    // Pitching line stump-to-stump (centre line down the pitch).
    _drawPolyline(
      canvas,
      [for (final p in overlay.centerline) map(p)],
      _blue.withValues(alpha: 0.75),
      1.6,
    );
    // Both wickets — yellow (3 stumps + bail).
    if (overlay.bowlerStumps != null) {
      _drawWicket(canvas, map(overlay.bowlerStumps!.base),
          map(overlay.bowlerStumps!.top), prominent: false);
    }
    if (overlay.strikerStumps != null) {
      _drawWicket(canvas, map(overlay.strikerStumps!.base),
          map(overlay.strikerStumps!.top), prominent: true);
    }

    // ---- ball path ----
    // Draw the RAW on-ball detections as the flight line — exactly like the
    // test3 validation render (server/scripts/test3_e2e.py). The smooth fit
    // projection (overlay.path phase=flight) can drift ~100 px off the real
    // ball near impact on phone footage, so the literal track is what sits on
    // the ball. Only the server's PREDICTED continuation is kept, anchored to
    // the last detection so it flows straight out of the ball — no jump, no
    // kink. One clean solid red curve, the broadcast look.
    final raw = List<BallTrackPoint>.of(track)
      ..sort((a, b) => a.t.compareTo(b.t));
    if (raw.length >= 2) {
      _drawPolyline(
        canvas,
        [for (final p in raw) map(p.p)],
        AppColors.signalRed,
        pathW,
      );
    } else {
      // Fallback when the raw track is unavailable: the fit-projected flight.
      _drawPolyline(
        canvas,
        [for (final p in overlay.path) if (!p.predicted) map(p.px)],
        AppColors.signalRed,
        pathW,
      );
    }

    final predicted = [for (final p in overlay.path) if (p.predicted) p];
    var shift = Offset.zero;
    if (predicted.isNotEmpty && raw.isNotEmpty) {
      // Anchor: translate the predicted polyline by the residual between the
      // last detection and the first predicted pixel, == _anchored_prediction_px.
      shift = raw.last.p - predicted.first.px;
      _drawPolyline(
        canvas,
        <Offset>[
          map(raw.last.p),
          for (final p in predicted) map(p.px + shift),
        ],
        AppColors.signalRed,
        pathW,
      );
    }

    if (overlay.bounce != null) {
      _drawBouncePin(canvas, map(overlay.bounce!.px));
    }

    // Moving ball rides the raw flight, then the anchored prediction, so the
    // cursor follows the whole visible curve to the stumps.
    final cursorPath = <OverlayPoint>[
      for (final p in raw) OverlayPoint(tMs: p.t, px: p.p, predicted: false),
      if (raw.isNotEmpty)
        for (final p in predicted)
          OverlayPoint(tMs: p.tMs, px: p.px + shift, predicted: true),
    ];
    final ball = _ballAt(
      cursorPath.isNotEmpty ? cursorPath : overlay.path,
      map,
      nowMs,
    );
    if (ball != null) {
      // Crisp white ball with a red ring — matches the validation render's
      // moving ball, no soft halo.
      canvas.drawCircle(ball, 8.5, Paint()..color = AppColors.bone);
      canvas.drawCircle(
        ball,
        8.5,
        Paint()
          ..style = PaintingStyle.stroke
          ..color = AppColors.signalRed
          ..strokeWidth = 2.5,
      );
    }
  }

  Offset? _ballAt(
    List<OverlayPoint> path,
    Offset Function(Offset) map,
    int t,
  ) {
    final samples = List<OverlayPoint>.of(path)
      ..sort((a, b) => a.tMs.compareTo(b.tMs));
    if (samples.length < 2) return null;
    if (t <= samples.first.tMs) return null;
    if (t >= samples.last.tMs) return map(samples.last.px);
    for (var i = 1; i < samples.length; i++) {
      final a = samples[i - 1];
      final b = samples[i];
      if (t >= a.tMs && t <= b.tMs) {
        final span = b.tMs - a.tMs;
        final f = span <= 0 ? 0.0 : (t - a.tMs) / span;
        return Offset.lerp(map(a.px), map(b.px), f);
      }
    }
    return null;
  }

  /// Three-stump wicket in yellow, scaled to the wicket's image height so the
  /// stump spread looks right in perspective (far wicket narrower than near).
  void _drawWicket(
    Canvas canvas,
    Offset base,
    Offset top, {
    required bool prominent,
  }) {
    final half = (0.16 * (base.dy - top.dy).abs()).clamp(4.0, 70.0);
    final width = prominent ? 4.0 : 3.0;
    const offs = <double>[-1, 0, 1];
    // No glow halo on either wicket — the striker (near-batsman) stumps used
    // to draw a soft yellow halo that read as "glowing"; both ends now render
    // as clean solid stumps, matching the bowler-end look.
    final stumpPaint = Paint()
      ..color = _yellow
      ..strokeCap = StrokeCap.round
      ..strokeWidth = width;
    for (final k in offs) {
      canvas.drawLine(
        base.translate(k * half, 0),
        top.translate(k * half, 0),
        stumpPaint,
      );
    }
    // bail across the tops
    canvas.drawLine(top.translate(-half, 0), top.translate(half, 0), stumpPaint);
  }

  void _drawPolygon(
    Canvas canvas,
    List<Offset> pts,
    Color color,
    double width,
  ) {
    if (pts.length < 2) return;
    canvas.drawPath(
      Path()..addPolygon(pts, true),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeJoin = StrokeJoin.round
        ..color = color
        ..strokeWidth = width,
    );
  }

  void _drawPolyline(
    Canvas canvas,
    List<Offset> pts,
    Color color,
    double width, {
    bool glow = false,
  }) {
    if (pts.length < 2) return;
    final path = Path()..moveTo(pts.first.dx, pts.first.dy);
    for (var i = 1; i < pts.length; i++) {
      path.lineTo(pts[i].dx, pts[i].dy);
    }
    if (glow) {
      canvas.drawPath(
        path,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeJoin = StrokeJoin.round
          ..strokeCap = StrokeCap.round
          ..color = color.withValues(alpha: 0.25)
          ..strokeWidth = width + 7.0,
      );
    }
    canvas.drawPath(
      path,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeJoin = StrokeJoin.round
        ..strokeCap = StrokeCap.round
        ..color = color
        ..strokeWidth = width,
    );
  }

  /// Bounce point — a flat solid red dot, no glow halo (matches the clean
  /// broadcast reference; the soft halo read as a "glow" at the bounce).
  void _drawBouncePin(Canvas canvas, Offset c) {
    canvas.drawCircle(c, 4.0, Paint()..color = AppColors.signalRed);
  }

  @override
  bool shouldRepaint(_OverlayPainter old) =>
      old.nowMs != nowMs ||
      old.overlay != overlay ||
      old.imageWidth != imageWidth;
}

class _MetricStack extends StatelessWidget {
  const _MetricStack({
    required this.metrics,
    required this.decision,
    required this.speedUnit,
  });
  final DeliveryMetrics metrics;
  final String? decision;
  final SpeedUnit speedUnit;

  @override
  Widget build(BuildContext context) {
    final speedValue = speedUnit == SpeedUnit.mph
        ? metrics.speedMph
        : metrics.speedKmh;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _MetricCard(
              icon: Icons.speed_rounded,
              label: 'Speed',
              value: speedValue.toStringAsFixed(0),
              unit: speedUnit.label,
            ),
            const SizedBox(width: 6),
            _MetricCard(
              icon: Icons.timeline_rounded,
              label: 'Swing',
              value: metrics.swingSf.toStringAsFixed(1),
              unit: '',
            ),
            const SizedBox(width: 6),
            _MetricCard(
              icon: Icons.rotate_right_rounded,
              label: 'Spin',
              value: metrics.spinDeg.toStringAsFixed(0),
              unit: 'deg',
            ),
          ],
        ),
        if (decision != null) ...[
          const SizedBox(height: 8),
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
      width: 86,
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: const Color(0xCC101012),
        borderRadius: BorderRadius.circular(10),
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
                  fontSize: 8.5,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 1.1,
                ),
              ),
              Icon(icon, size: 12, color: AppColors.ash),
            ],
          ),
          const SizedBox(height: 2),
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Text(
                value,
                style: const TextStyle(
                  color: AppColors.bone,
                  fontSize: 16,
                  fontWeight: FontWeight.w800,
                  height: 1.0,
                ),
              ),
              const SizedBox(width: 3),
              Text(
                unit,
                style: const TextStyle(
                  color: AppColors.bone,
                  fontSize: 9.5,
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
      width: 96,
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: const Color(0xCC101012),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color, width: 1.2),
      ),
      child: Text(
        label,
        textAlign: TextAlign.center,
        style: TextStyle(
          color: color,
          fontSize: 11,
          fontWeight: FontWeight.w800,
          letterSpacing: 1.2,
        ),
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
          child: Icon(
            playing ? Icons.pause : Icons.replay,
            color: AppColors.bone,
            size: 22,
          ),
        ),
      ),
    );
  }
}
