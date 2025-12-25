import 'dart:ui';

class PitchCalibration {
  const PitchCalibration({
    required this.imagePoints,
  });

  /// Four points in image coordinates (pixels), in order:
  /// 0: striker end - left
  /// 1: striker end - right
  /// 2: bowler end - right
  /// 3: bowler end - left
  final List<Offset> imagePoints;

  /// Validates that the 4 taps form a non-degenerate, convex quadrilateral.
  ///
  /// This does **not** compute a homography. The authoritative pitch-plane
  /// mapping is produced by the backend pipeline.
  void validateImageQuad() {
    if (imagePoints.length != 4) {
      throw StateError('Pitch calibration requires exactly 4 taps');
    }

    // Shoelace area (in px^2)
    var area2 = 0.0;
    for (var i = 0; i < 4; i++) {
      final a = imagePoints[i];
      final b = imagePoints[(i + 1) % 4];
      area2 += (a.dx * b.dy - b.dx * a.dy);
    }
    if (area2.abs() < 250.0) {
      throw StateError('Pitch taps are too close together (degenerate quad)');
    }

    // Convexity check: all cross products should have the same sign.
    double? sign;
    for (var i = 0; i < 4; i++) {
      final p0 = imagePoints[i];
      final p1 = imagePoints[(i + 1) % 4];
      final p2 = imagePoints[(i + 2) % 4];
      final cross = (p1.dx - p0.dx) * (p2.dy - p1.dy) - (p1.dy - p0.dy) * (p2.dx - p1.dx);
      if (cross.abs() < 1e-6) {
        throw StateError('Pitch taps are nearly collinear');
      }
      sign ??= cross.sign;
      if (cross.sign != sign) {
        throw StateError('Pitch taps must form a convex quadrilateral');
      }
    }
  }

  Map<String, Object?> toJson() {
    return <String, Object?>{
      'imagePoints': imagePoints
          .map((p) => <String, Object?>{'x': p.dx, 'y': p.dy})
          .toList(growable: false),
    };
  }

  static PitchCalibration fromJson(Map<String, Object?> json) {
    final raw = json['imagePoints'];
    if (raw is! List) throw FormatException('Expected imagePoints');
    final pts = <Offset>[];
    for (final v in raw) {
      if (v is! Map) throw FormatException('Invalid point');
      final x = v['x'];
      final y = v['y'];
      if (x is! num || y is! num) throw FormatException('Invalid point values');
      pts.add(Offset(x.toDouble(), y.toDouble()));
    }
    if (pts.length != 4) throw FormatException('Expected 4 points');
    return PitchCalibration(imagePoints: pts);
  }
}
