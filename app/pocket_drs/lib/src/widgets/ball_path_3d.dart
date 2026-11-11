import 'dart:math' as math;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import '../api/analysis_result.dart';
import '../theme/app_colors.dart';
import '../utils/app_settings.dart';

const _pitchHalfWidthM = 3.05 / 2;
const _poppingM = 1.22;
const _creaseHalfM = 1.32;
const _stumpRadiusM = 0.0175;
const _ballRadiusM = 0.036;
const _near = 0.05;
const _halfFov = 12 * math.pi / 180;
const _minPitch = 0.03;
const _maxPitch = 1.45;
const _minZoom = 0.2;
const _maxZoom = 1.6;
const _target = _V3(1.0, 0, 0.35);

// the default eye sits 12 m behind the bowler's stumps and 5 m up, like a TV replay
_V3 _defaultOffset(double pitchL) => _V3(pitchL + 12, 0, 5) - _target;

/// A 3D replay of the ball path drawn from the saved result, so it works offline.
class BallPath3D extends StatefulWidget {
  const BallPath3D({
    super.key,
    required this.result,
    required this.pitchLengthM,
    required this.stumps,
  });

  final AnalysisResult result;
  final double pitchLengthM;
  final StumpSize stumps;

  @override
  State<BallPath3D> createState() => _BallPath3DState();
}

class _BallPath3DState extends State<BallPath3D>
    with SingleTickerProviderStateMixin {
  late final AnimationController _play = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1500),
  );
  late _Scene _scene = _Scene.from(widget.result);
  double _yaw = 0;
  late double _pitch = _homePitch;
  double _zoom = 1;
  double _zoomAtStart = 1;
  bool _started = false;

  double get _pitchL => widget.pitchLengthM.isFinite && widget.pitchLengthM > 1
      ? widget.pitchLengthM
      : 20.12;

  double get _homePitch {
    final d = _defaultOffset(_pitchL);
    return math.atan2(d.z, d.x).clamp(_minPitch, _maxPitch);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_started) {
      _started = true;
      _replay();
    }
  }

  @override
  void didUpdateWidget(BallPath3D old) {
    super.didUpdateWidget(old);
    if (old.result != widget.result) {
      _scene = _Scene.from(widget.result);
      _replay();
    }
  }

  @override
  void dispose() {
    _play.dispose();
    super.dispose();
  }

  void _replay() {
    if (MediaQuery.disableAnimationsOf(context)) {
      _play.value = 1;
    } else {
      _play.forward(from: 0);
    }
  }

  void _reset() => setState(() {
    _yaw = 0;
    _pitch = _homePitch;
    _zoom = 1;
  });

  void _onScaleUpdate(ScaleUpdateDetails d) => setState(() {
    if (d.pointerCount >= 2) {
      if (d.scale > 0) {
        _zoom = (_zoomAtStart / d.scale).clamp(_minZoom, _maxZoom);
      }
    } else {
      _yaw -= d.focalPointDelta.dx * 0.008;
      _pitch = (_pitch + d.focalPointDelta.dy * 0.006).clamp(
        _minPitch,
        _maxPitch,
      );
    }
  });

  void _onPointerSignal(PointerSignalEvent e) {
    if (e is PointerScrollEvent) {
      setState(() {
        _zoom = (_zoom * math.exp(e.scrollDelta.dy * 0.0015)).clamp(
          _minZoom,
          _maxZoom,
        );
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_scene.tracked.isEmpty) {
      return ColoredBox(
        color: AppColors.video,
        child: Center(
          child: Text(
            'No ball path to show.',
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: AppColors.onVideo),
          ),
        ),
      );
    }
    final still = MediaQuery.disableAnimationsOf(context);
    final verdict = AppColors.verdict(widget.result.lbw?.decision);
    return Semantics(
      label: '3D ball path. Drag to turn, pinch to zoom, double tap to reset.',
      child: ColoredBox(
        color: AppColors.video,
        child: Stack(
          fit: StackFit.expand,
          children: [
            Listener(
              onPointerSignal: _onPointerSignal,
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onScaleStart: (_) => _zoomAtStart = _zoom,
                onScaleUpdate: _onScaleUpdate,
                onDoubleTap: _reset,
                child: AnimatedBuilder(
                  animation: _play,
                  builder: (_, _) => CustomPaint(
                    size: Size.infinite,
                    painter: _Painter(
                      scene: _scene,
                      pitchL: _pitchL,
                      stumps: widget.stumps,
                      verdict: verdict,
                      progress: _play.value,
                      yaw: _yaw,
                      pitch: _pitch,
                      zoom: _zoom,
                    ),
                  ),
                ),
              ),
            ),
            if (!still)
              Positioned(
                right: 6,
                bottom: 6,
                child: IconButton(
                  onPressed: _replay,
                  tooltip: 'Replay',
                  iconSize: 20,
                  visualDensity: VisualDensity.compact,
                  color: AppColors.onVideo,
                  style: IconButton.styleFrom(
                    backgroundColor: AppColors.videoPanel,
                  ),
                  icon: const Icon(Icons.replay),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _V3 {
  const _V3(this.x, this.y, this.z);
  final double x, y, z;

  _V3 operator +(_V3 o) => _V3(x + o.x, y + o.y, z + o.z);
  _V3 operator -(_V3 o) => _V3(x - o.x, y - o.y, z - o.z);
  _V3 operator *(double k) => _V3(x * k, y * k, z * k);
  double dot(_V3 o) => x * o.x + y * o.y + z * o.z;
  _V3 cross(_V3 o) =>
      _V3(y * o.z - z * o.y, z * o.x - x * o.z, x * o.y - y * o.x);
  double get length => math.sqrt(dot(this));
  _V3 get unit {
    final l = length;
    return l == 0 ? this : this * (1 / l);
  }

  bool get isFinite => x.isFinite && y.isFinite && z.isFinite;
  _V3 get onGround => _V3(x, y, 0);

  static _V3 lerp(_V3 a, _V3 b, double t) => a + (b - a) * t;
}

List<double> _cumulative(List<_V3> pts) {
  final out = <double>[];
  var s = 0.0;
  for (var i = 0; i < pts.length; i++) {
    if (i > 0) s += (pts[i] - pts[i - 1]).length;
    out.add(s);
  }
  return out;
}

// the polyline cut off at arc length s
List<_V3> _upTo(List<_V3> pts, List<double> cum, double s) {
  if (pts.isEmpty || s < 0) return const [];
  if (s >= cum.last) return pts;
  final out = <_V3>[pts.first];
  for (var i = 1; i < pts.length; i++) {
    if (cum[i] >= s) {
      final seg = cum[i] - cum[i - 1];
      out.add(
        seg <= 0
            ? pts[i]
            : _V3.lerp(pts[i - 1], pts[i], (s - cum[i - 1]) / seg),
      );
      break;
    }
    out.add(pts[i]);
  }
  return out;
}

// dashes are cut in metres so they shrink with distance like the rest of the scene
List<List<_V3>> _dashes(List<_V3> pts, double on, double off) {
  final out = <List<_V3>>[];
  if (pts.length < 2) return out;
  var cur = <_V3>[pts.first];
  var drawing = true;
  var left = on;
  for (var i = 0; i + 1 < pts.length; i++) {
    var a = pts[i];
    final b = pts[i + 1];
    var rest = (b - a).length;
    while (rest > left) {
      final p = _V3.lerp(a, b, left / rest);
      if (drawing) {
        cur.add(p);
        out.add(cur);
      }
      cur = <_V3>[p];
      drawing = !drawing;
      rest -= left;
      a = p;
      left = drawing ? on : off;
    }
    left -= rest;
    if (drawing) cur.add(b);
  }
  if (drawing && cur.length >= 2) out.add(cur);
  return out;
}

class _Scene {
  _Scene._({
    required this.tracked,
    required this.predicted,
    required this.bounce,
    required this.impact,
    required this.atStumps,
  }) : trackedCum = _cumulative(tracked),
       predictedCum = _cumulative(predicted);

  factory _Scene.from(AnalysisResult r) {
    List<_V3> pts(List<WorldPointM> src) => [
      for (final p in src) _V3(p.x, p.y, p.z),
    ].where((v) => v.isFinite).toList(growable: false);
    final tracked = pts(r.worldTrajectory.points);
    final predicted = pts(r.worldTrajectory.predictedToStumps);
    final all = [...tracked, ...predicted];

    double? zAtX(double x) {
      for (var i = 0; i + 1 < all.length; i++) {
        final a = all[i], b = all[i + 1];
        if ((a.x - x) * (b.x - x) <= 0 && a.x != b.x) {
          return a.z + (b.z - a.z) * (x - a.x) / (b.x - a.x);
        }
      }
      return null;
    }

    _V3? event(EventPointM? e, {required bool ground}) {
      if (e == null || !e.xM.isFinite || !e.yM.isFinite) return null;
      final z = ground ? 0.0 : (e.zM ?? zAtX(e.xM) ?? _ballRadiusM);
      final v = _V3(e.xM, e.yM, z);
      return v.isFinite ? v : null;
    }

    _V3? atStumps;
    for (var i = 0; i + 1 < all.length; i++) {
      final a = all[i], b = all[i + 1];
      if (a.x > 0 && b.x <= 0) {
        atStumps = _V3.lerp(a, b, a.x / (a.x - b.x));
        break;
      }
    }
    if (atStumps == null && all.isNotEmpty && all.last.x.abs() < 0.3) {
      atStumps = all.last;
    }

    return _Scene._(
      tracked: tracked,
      predicted: predicted,
      bounce: event(r.events?.bounce, ground: true),
      impact: event(r.events?.impact, ground: false),
      atStumps: atStumps,
    );
  }

  final List<_V3> tracked, predicted;
  final List<double> trackedCum, predictedCum;
  final _V3? bounce, impact, atStumps;

  double get trackedLen => trackedCum.isEmpty ? 0 : trackedCum.last;
  double get total =>
      trackedLen + (predictedCum.isEmpty ? 0 : predictedCum.last);

  // arc length of the path vertex nearest p, so a marker appears as the ball passes it
  double arcOf(_V3 p) {
    var best = double.infinity;
    var s = 0.0;
    for (var i = 0; i < tracked.length; i++) {
      final d = (tracked[i] - p).length;
      if (d < best) (best, s) = (d, trackedCum[i]);
    }
    for (var i = 0; i < predicted.length; i++) {
      final d = (predicted[i] - p).length;
      if (d < best) (best, s) = (d, trackedLen + predictedCum[i]);
    }
    return s;
  }
}

class _Camera {
  factory _Camera(Size size, double dist, double yaw, double pitch) {
    final cp = math.cos(pitch);
    final eye =
        _target +
        _V3(cp * math.cos(yaw), cp * math.sin(yaw), math.sin(pitch)) * dist;
    final fwd = (_target - eye).unit;
    final right = fwd.cross(const _V3(0, 0, 1)).unit;
    return _Camera._(
      eye,
      right,
      right.cross(fwd),
      fwd,
      0.5 * math.min(size.width, size.height) / math.tan(_halfFov),
      // a little above centre leaves room for the near end of the pitch
      Offset(size.width / 2, size.height * 0.42),
    );
  }

  _Camera._(this.eye, this.right, this.up, this.fwd, this.focal, this.centre);

  final _V3 eye, right, up, fwd;
  final double focal;
  final Offset centre;

  _V3 view(_V3 p) {
    final d = p - eye;
    return _V3(d.dot(right), d.dot(up), d.dot(fwd));
  }

  Offset screen(_V3 c) =>
      Offset(centre.dx + focal * c.x / c.z, centre.dy - focal * c.y / c.z);
}

// cuts a view-space segment at the near plane so nothing behind the eye is drawn mirrored
(_V3, _V3)? _clipSegment(_V3 a, _V3 b) {
  if (a.z < _near && b.z < _near) return null;
  if (a.z < _near) return (_V3.lerp(a, b, (_near - a.z) / (b.z - a.z)), b);
  if (b.z < _near) return (a, _V3.lerp(b, a, (_near - b.z) / (a.z - b.z)));
  return (a, b);
}

List<_V3> _clipPolygon(List<_V3> poly) {
  final out = <_V3>[];
  for (var i = 0; i < poly.length; i++) {
    final a = poly[i], b = poly[(i + 1) % poly.length];
    final aIn = a.z >= _near, bIn = b.z >= _near;
    if (aIn) out.add(a);
    if (aIn != bIn) out.add(_V3.lerp(a, b, (_near - a.z) / (b.z - a.z)));
  }
  return out;
}

class _Painter extends CustomPainter {
  _Painter({
    required this.scene,
    required this.pitchL,
    required this.stumps,
    required this.verdict,
    required this.progress,
    required this.yaw,
    required this.pitch,
    required this.zoom,
  });

  final _Scene scene;
  final double pitchL;
  final StumpSize stumps;
  final Color? verdict;
  final double progress;
  final double yaw, pitch, zoom;

  late _Camera _cam;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.width <= 0 || size.height <= 0) return;
    canvas.clipRect(Offset.zero & size);
    _cam = _Camera(size, _defaultOffset(pitchL).length * zoom, yaw, pitch);

    _drawPitch(canvas);
    final zone = verdict;
    if (zone != null) {
      final w = stumps.widthM / 2, h = stumps.heightM;
      _fill(canvas, [
        _V3(0, -w, 0),
        _V3(0, w, 0),
        _V3(0, w, h),
        _V3(0, -w, h),
      ], zone.withValues(alpha: 0.16));
    }
    _drawStumps(canvas, pitchL, AppColors.onVideo.withValues(alpha: 0.7));
    _drawStumps(canvas, 0, AppColors.onVideo.withValues(alpha: 0.9));

    final total = scene.total;
    final done = progress >= 1 || total <= 0;
    final s = done ? double.infinity : progress * total;
    final tracked = _upTo(scene.tracked, scene.trackedCum, s);
    final predicted = _upTo(
      scene.predicted,
      scene.predictedCum,
      s - scene.trackedLen,
    );
    final dashes = _dashes(predicted, 0.22, 0.16);

    final shadow = Colors.black.withValues(alpha: 0.35);
    _tube(canvas, [for (final p in tracked) p.onGround], shadow);
    for (final d in dashes) {
      _tube(canvas, [for (final p in d) p.onGround], shadow);
    }

    final ring = AppColors.onVideo.withValues(alpha: 0.85);
    final b = scene.bounce;
    if (b != null && (done || s >= scene.arcOf(b))) {
      _ring(canvas, b, const _V3(1, 0, 0), const _V3(0, 1, 0), 0.12, ring);
    }

    _tube(canvas, tracked, AppColors.track);
    for (final d in dashes) {
      _tube(canvas, d, AppColors.predicted);
    }

    final i = scene.impact;
    if (i != null && (done || s >= scene.arcOf(i))) {
      _ring(canvas, i, const _V3(0, 1, 0), const _V3(0, 0, 1), 0.11, ring);
    }

    final hit = scene.atStumps;
    if (hit != null && done) {
      _ball(canvas, hit, AppColors.predicted, 4);
      _ring(
        canvas,
        hit,
        const _V3(0, 1, 0),
        const _V3(0, 0, 1),
        0.075,
        verdict ?? ring,
      );
    }

    if (!done) {
      final head = predicted.isNotEmpty
          ? predicted.last
          : (tracked.isNotEmpty ? tracked.last : null);
      if (head != null) {
        _ball(
          canvas,
          head,
          predicted.isNotEmpty ? AppColors.predicted : AppColors.track,
          3.5,
        );
      }
    }
  }

  void _drawPitch(Canvas canvas) {
    const g = 15.0;
    _fill(canvas, [
      const _V3(-g, -g, 0),
      _V3(pitchL + g, -g, 0),
      _V3(pitchL + g, g, 0),
      const _V3(-g, g, 0),
    ], AppColors.onVideo.withValues(alpha: 0.025));
    const ends = 1.83;
    _fill(canvas, [
      const _V3(-ends, -_pitchHalfWidthM, 0),
      _V3(pitchL + ends, -_pitchHalfWidthM, 0),
      _V3(pitchL + ends, _pitchHalfWidthM, 0),
      const _V3(-ends, _pitchHalfWidthM, 0),
    ], AppColors.onVideo.withValues(alpha: 0.07));

    final line = Paint()
      ..color = AppColors.onVideo.withValues(alpha: 0.45)
      ..strokeWidth = 1.2
      ..strokeCap = StrokeCap.round;
    for (final (e, dir) in [(0.0, 1.0), (pitchL, -1.0)]) {
      final pop = e + dir * _poppingM;
      final back = e - dir * (2.44 - _poppingM);
      _line(canvas, _V3(e, -_creaseHalfM, 0), _V3(e, _creaseHalfM, 0), line);
      _line(
        canvas,
        _V3(pop, -_pitchHalfWidthM, 0),
        _V3(pop, _pitchHalfWidthM, 0),
        line,
      );
      for (final y in [-_creaseHalfM, _creaseHalfM]) {
        _line(canvas, _V3(pop, y, 0), _V3(back, y, 0), line);
      }
    }
  }

  void _drawStumps(Canvas canvas, double x, Color color) {
    final half = stumps.widthM / 2;
    final h = stumps.heightM;
    final edge = math.max(0.0, half - _stumpRadiusM);
    final paint = Paint()
      ..color = color
      ..strokeCap = StrokeCap.butt;
    for (final y in [-edge, 0.0, edge]) {
      _line(
        canvas,
        _V3(x, y, 0),
        _V3(x, y, h),
        paint,
        widthM: 2 * _stumpRadiusM,
        minPx: 1.2,
      );
    }
    _line(
      canvas,
      _V3(x, -half, h + 0.008),
      _V3(x, half, h + 0.008),
      paint,
      widthM: 0.012,
      minPx: 1,
    );
  }

  // with widthM the stroke follows perspective, otherwise it keeps the paint's width
  void _line(
    Canvas canvas,
    _V3 a,
    _V3 b,
    Paint paint, {
    double? widthM,
    double minPx = 1,
  }) {
    final seg = _clipSegment(_cam.view(a), _cam.view(b));
    if (seg == null) return;
    final (va, vb) = seg;
    if (widthM != null) {
      final depth = (va.z + vb.z) / 2;
      paint.strokeWidth = (_cam.focal * widthM / depth).clamp(minPx, 60.0);
    }
    canvas.drawLine(_cam.screen(va), _cam.screen(vb), paint);
  }

  void _fill(Canvas canvas, List<_V3> world, Color color) {
    final poly = _clipPolygon([for (final p in world) _cam.view(p)]);
    if (poly.length < 3) return;
    final path = Path()
      ..addPolygon([for (final p in poly) _cam.screen(p)], true);
    canvas.drawPath(path, Paint()..color = color);
  }

  void _tube(Canvas canvas, List<_V3> pts, Color color) {
    if (pts.isEmpty) return;
    final paint = Paint()
      ..color = color
      ..strokeCap = StrokeCap.round;
    if (pts.length == 1) {
      _ball(canvas, pts.first, color, 2);
      return;
    }
    for (var i = 0; i + 1 < pts.length; i++) {
      _line(
        canvas,
        pts[i],
        pts[i + 1],
        paint,
        widthM: 2 * _ballRadiusM,
        minPx: 2.5,
      );
    }
  }

  void _ball(Canvas canvas, _V3 p, Color color, double minPx) {
    final v = _cam.view(p);
    if (v.z < _near) return;
    final r = (_cam.focal * _ballRadiusM / v.z).clamp(minPx, 60.0);
    canvas.drawCircle(_cam.screen(v), r, Paint()..color = color);
  }

  void _ring(Canvas canvas, _V3 c, _V3 u, _V3 v, double r, Color color) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5;
    const n = 32;
    _V3 at(int k) {
      final t = 2 * math.pi * k / n;
      return c + u * (r * math.cos(t)) + v * (r * math.sin(t));
    }

    for (var k = 0; k < n; k++) {
      _line(canvas, at(k), at(k + 1), paint);
    }
  }

  @override
  bool shouldRepaint(_Painter old) =>
      old.scene != scene ||
      old.pitchL != pitchL ||
      old.stumps != stumps ||
      old.verdict != verdict ||
      old.progress != progress ||
      old.yaw != yaw ||
      old.pitch != pitch ||
      old.zoom != zoom;
}
