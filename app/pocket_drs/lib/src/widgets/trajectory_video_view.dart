import 'dart:io';
import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../analysis/ball_track_models.dart';
import '../api/analysis_result.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../utils/app_settings.dart';

/// The clip with the tracked ball path and its predicted path to the stumps
/// drawn over it, plus speed, spin and swing tiles.
class TrajectoryVideoView extends StatefulWidget {
  const TrajectoryVideoView({
    super.key,
    required this.videoPath,
    required this.result,
  });

  final String videoPath;
  final AnalysisResult result;

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
    final controller = VideoPlayerController.file(File(widget.videoPath));
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
        ? lastT + 1200
        : (lastT + 1200).clamp(0, durationMs);
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
        child: Text(
          _error!,
          style: Theme.of(
            context,
          ).textTheme.bodyMedium?.copyWith(color: AppColors.onVideo),
        ),
      );
    }
    final c = _controller;
    if (c == null || !c.value.isInitialized) {
      return const Center(
        child: CircularProgressIndicator(color: AppColors.onVideo),
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
            // a faint scrim so the overlay lines stay legible on a bright scene
            ColoredBox(color: AppColors.video.withValues(alpha: 0x14 / 0xFF)),
            if (overlay != null && imgW > 0 && imgH > 0)
              CustomPaint(
                painter: _OverlayPainter(
                  overlay: overlay,
                  track: widget.result.track.points,
                  lbw: widget.result.lbw,
                  imageWidth: imgW,
                  imageHeight: imgH,
                  nowMs: nowMs,
                ),
              ),
            if (metrics != null)
              Positioned(
                top: 14,
                left: 12,
                right: 12,
                // a tall narrow clip leaves less room than three cards need
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.topLeft,
                  child: _MetricStack(metrics: metrics, speedUnit: _speedUnit),
                ),
              ),
            Positioned(
              right: 8,
              bottom: 8,
              child: IconButton.filledTonal(
                tooltip: c.value.isPlaying ? 'Pause' : 'Replay',
                icon: Icon(c.value.isPlaying ? Icons.pause : Icons.replay),
                onPressed: () {
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
    required this.lbw,
    required this.imageWidth,
    required this.imageHeight,
    required this.nowMs,
  });

  final TrajectoryOverlay overlay;

  /// Raw on-ball detections in pixel space. They sit on the ball, where the
  /// fitted projection can drift near impact, so they make the trail.
  final List<BallTrackPoint> track;
  final LbwResult? lbw;
  final double imageWidth;
  final double imageHeight;
  final int nowMs;

  static const _popMs = 320;

  // a row's colour: against the batter is out red, for him not out green
  Color _tone(String row) => switch (lbw?.tones[row]) {
    'out' => AppColors.out,
    'not_out' => AppColors.notOut,
    'umpires_call' => AppColors.umpiresCall,
    _ => AppColors.onVideo,
  };

  static double _easeOut(double k) {
    final c = k.clamp(0.0, 1.0);
    return 1 - (1 - c) * (1 - c) * (1 - c);
  }

  // the points up to time t, ending exactly where the ball is now
  static List<Offset> _upTo(List<OverlayPoint> pts, int t) {
    if (pts.isEmpty || t < pts.first.tMs) return const [];
    final out = <Offset>[pts.first.px];
    for (var i = 1; i < pts.length; i++) {
      final a = pts[i - 1], b = pts[i];
      if (b.tMs <= t) {
        out.add(b.px);
        continue;
      }
      final span = b.tMs - a.tMs;
      out.add(Offset.lerp(a.px, b.px, span <= 0 ? 0 : (t - a.tMs) / span)!);
      break;
    }
    return out;
  }

  @override
  void paint(Canvas canvas, Size size) {
    // the projected pitch runs off the frame when the phone stands close to the stumps
    canvas.clipRect(Offset.zero & size);
    final sx = size.width / imageWidth;
    final sy = size.height / imageHeight;
    Offset map(Offset p) => Offset(p.dx * sx, p.dy * sy);
    // tuned on a 1080-wide frame, so the line keeps its weight on any screen
    final w = (6.0 * sx).clamp(2.5, 6.0);

    // faint calibration context under the ball: the pitch and the stump-to-stump channel
    final rect = [for (final p in overlay.pitchRect) map(p)];
    if (rect.length >= 3) {
      canvas.drawPath(
        Path()..addPolygon(rect, true),
        _stroke(AppColors.onVideo.withValues(alpha: 0.28), 1.2),
      );
    }
    final corridor = [for (final p in overlay.corridor) map(p)];
    if (corridor.length >= 4) {
      canvas.drawPath(
        Path()..addPolygon(corridor, true),
        Paint()..color = AppColors.onVideo.withValues(alpha: 0.08),
      );
    }

    final flight = [
      for (final p in track) OverlayPoint(tMs: p.t, px: p.p, predicted: false),
    ]..sort((a, b) => a.tMs.compareTo(b.tMs));
    if (flight.length < 2) {
      flight
        ..clear()
        ..addAll(overlay.path.where((p) => !p.predicted));
    }
    // the ball often hides as it pitches, so route the trail through the bounce
    final bounce = overlay.bounce;
    if (bounce != null &&
        flight.length >= 2 &&
        bounce.tMs > flight.first.tMs &&
        bounce.tMs < flight.last.tMs) {
      flight.insert(flight.indexWhere((p) => p.tMs > bounce.tMs), bounce);
    }
    // the prediction comes from the fit; shift it onto the trail's end so the two join without a jump
    final predicted = overlay.path.where((p) => p.predicted).toList();
    final ahead = <OverlayPoint>[
      if (flight.isNotEmpty && predicted.isNotEmpty) ...[
        flight.last,
        for (final p in predicted)
          OverlayPoint(
            tMs: p.tMs,
            px: p.px + (flight.last.px - predicted.first.px),
            predicted: true,
          ),
      ],
    ];
    if (flight.isEmpty) return;
    final flightEnd = flight.last.tMs;
    final aheadEnd = ahead.isEmpty ? flightEnd : ahead.last.tMs;
    double pop(int at) => (nowMs - at) / _popMs;

    final trail = [for (final p in _upTo(flight, nowMs)) map(p)];
    _polyline(
      canvas,
      trail,
      _stroke(AppColors.track.withValues(alpha: 0.22), w * 3.2),
    );
    _polyline(canvas, trail, _stroke(AppColors.track, w));
    _polyline(
      canvas,
      trail,
      _stroke(AppColors.onVideo.withValues(alpha: 0.55), w * 0.3),
    );

    final pred = nowMs >= flightEnd
        ? [for (final p in _upTo(ahead, nowMs)) map(p)]
        : const <Offset>[];
    _polyline(
      canvas,
      pred,
      _stroke(AppColors.track.withValues(alpha: 0.14), w * 2.4),
    );
    _polyline(
      canvas,
      pred,
      _stroke(AppColors.track.withValues(alpha: 0.75), w * 0.9),
      dash: w * 1.6,
      gap: w * 1.4,
    );

    if (bounce != null && nowMs >= bounce.tMs) {
      final k = _easeOut(pop(bounce.tMs));
      final c = _tone('pitching');
      final at = map(bounce.px);
      canvas.drawCircle(at, w * 1.8 * (0.4 + 0.6 * k), Paint()..color = c);
      canvas.drawCircle(
        at,
        w * 3.4 * (0.6 + 0.4 * k),
        _stroke(c.withValues(alpha: 0.9), (w * 0.5).clamp(1.5, 4.0)),
      );
    }
    final impact = overlay.impact;
    if (impact != null && nowMs >= impact.tMs) {
      final k = pop(impact.tMs);
      final c = _tone('impact');
      final at = map(impact.px);
      canvas.drawCircle(at, w * 2.8, _stroke(c, (w * 0.6).clamp(2.0, 5.0)));
      if (k < 1) {
        canvas.drawCircle(
          at,
          w * (2.8 + 5 * _easeOut(k)),
          _stroke(c.withValues(alpha: 1 - k), (w * 0.45).clamp(1.5, 4.0)),
        );
      }
    }
    final striker = overlay.strikerStumps;
    if (ahead.isNotEmpty && striker != null && nowMs >= aheadEnd) {
      _drawWicket(
        canvas,
        map(striker.base),
        map(striker.top),
        _tone('wickets'),
        _easeOut(pop(aheadEnd)),
        w,
      );
    }

    // the ball, riding the head of whichever path is being drawn
    final head = pred.length >= 2
        ? pred.last
        : (trail.isEmpty ? null : trail.last);
    if (head != null && nowMs <= aheadEnd + 400) {
      canvas.drawCircle(
        head,
        w * 2.2,
        Paint()..color = AppColors.track.withValues(alpha: 0.35),
      );
      canvas.drawCircle(head, w * 1.4, Paint()..color = AppColors.onVideo);
      canvas.drawCircle(
        head,
        w * 1.4,
        _stroke(AppColors.track, (w * 0.4).clamp(1.5, 3.0)),
      );
    }
  }

  /// The striker's wicket lit in the wickets colour once the path arrives.
  void _drawWicket(
    Canvas canvas,
    Offset base,
    Offset top,
    Color c,
    double k,
    double w,
  ) {
    final half = (0.16 * (base.dy - top.dy).abs()).clamp(4.0, 70.0);
    canvas.drawRect(
      Rect.fromLTRB(top.dx - half, top.dy, top.dx + half, base.dy),
      Paint()..color = c.withValues(alpha: 0.25 * k),
    );
    final p = _stroke(c.withValues(alpha: k), (w * 0.5).clamp(2.0, 4.0));
    for (final d in const [-1.0, 0.0, 1.0]) {
      canvas.drawLine(
        base.translate(d * half, 0),
        top.translate(d * half, 0),
        p,
      );
    }
    canvas.drawLine(top.translate(-half, 0), top.translate(half, 0), p);
  }

  static Paint _stroke(Color c, double width) => Paint()
    ..style = PaintingStyle.stroke
    ..strokeJoin = StrokeJoin.round
    ..strokeCap = StrokeCap.round
    ..color = c
    ..strokeWidth = width;

  void _polyline(
    Canvas canvas,
    List<Offset> pts,
    Paint paint, {
    double? dash,
    double gap = 0,
  }) {
    if (pts.length < 2) return;
    final path = Path()..moveTo(pts.first.dx, pts.first.dy);
    for (var i = 1; i < pts.length; i++) {
      path.lineTo(pts[i].dx, pts[i].dy);
    }
    if (dash == null) {
      canvas.drawPath(path, paint);
      return;
    }
    for (final m in path.computeMetrics()) {
      for (var d = 0.0; d < m.length; d += dash + gap) {
        canvas.drawPath(m.extractPath(d, d + dash), paint);
      }
    }
  }

  @override
  bool shouldRepaint(_OverlayPainter old) =>
      old.nowMs != nowMs ||
      old.overlay != overlay ||
      old.lbw != lbw ||
      old.imageWidth != imageWidth;
}

class _MetricStack extends StatelessWidget {
  const _MetricStack({required this.metrics, required this.speedUnit});
  final DeliveryMetrics metrics;
  final SpeedUnit speedUnit;

  @override
  Widget build(BuildContext context) {
    final speedValue = speedUnit == SpeedUnit.mph
        ? metrics.speedMph
        : metrics.speedKmh;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _MetricCard(
          icon: Icons.speed_rounded,
          label: 'Speed',
          value: speedValue?.toStringAsFixed(0) ?? '–',
          unit: speedUnit.label,
        ),
        const SizedBox(width: 6),
        _MetricCard(
          icon: Icons.timeline_rounded,
          label: 'Swing',
          value: metrics.swingCm?.toStringAsFixed(1) ?? '–',
          unit: 'cm',
        ),
        const SizedBox(width: 6),
        _MetricCard(
          icon: Icons.rotate_right_rounded,
          label: 'Spin',
          value: metrics.spinDeg?.toStringAsFixed(0) ?? '–',
          unit: 'deg',
        ),
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
    final text = Theme.of(context).textTheme;
    final dim = AppColors.onVideo.withValues(alpha: 0.7);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: AppColors.video.withValues(alpha: 0.6),
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(label, style: text.labelSmall?.copyWith(color: dim)),
              const SizedBox(width: 4),
              Icon(icon, size: 12, color: dim),
            ],
          ),
          const SizedBox(height: 2),
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Text(
                value,
                style: AppTheme.tabular(
                  text.titleMedium,
                )?.copyWith(color: AppColors.onVideo),
              ),
              const SizedBox(width: 3),
              Text(unit, style: text.labelSmall?.copyWith(color: dim)),
            ],
          ),
        ],
      ),
    );
  }
}
