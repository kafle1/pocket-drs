import 'dart:ui';

class PitchCalibration {
  const PitchCalibration({
    required this.imagePoints,
    this.stumpPoints,
    this.imageSizePx,
    this.imagePointsNorm,
    this.stumpPointsNorm,
  });

  /// Four pitch corner points in image coordinates (pixels):
  /// 0: top-left, 1: top-right, 2: bottom-right, 3: bottom-left
  final List<Offset> imagePoints;

  /// Optional stump marker points in image coordinates (pixels):
  /// 0: near stump base, 1: near stump top, 2: far stump base, 3: far stump top
  final List<Offset>? stumpPoints;

  /// Source image size used to interpret [imagePoints] and [stumpPoints].
  ///
  /// When set together with normalized points, the calibration can be
  /// re-scaled to other videos reliably.
  final Size? imageSizePx;

  /// Normalized pitch corner points in [0..1] relative to the source image.
  ///
  /// Order must match [imagePoints].
  final List<Offset>? imagePointsNorm;

  /// Normalized stump points in [0..1] relative to the source image.
  ///
  /// Order must match [stumpPoints].
  final List<Offset>? stumpPointsNorm;

  void validateImageQuad() {
    if (imagePoints.length != 4) {
      throw StateError('Pitch calibration requires exactly 4 taps');
    }

    var area2 = 0.0;
    for (var i = 0; i < 4; i++) {
      final a = imagePoints[i];
      final b = imagePoints[(i + 1) % 4];
      area2 += (a.dx * b.dy - b.dx * a.dy);
    }
    if (area2.abs() < 250.0) {
      throw StateError('Pitch taps are too close together');
    }

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
      'imagePoints': imagePoints.map((p) => {'x': p.dx, 'y': p.dy}).toList(),
      if (stumpPoints != null)
        'stumpPoints': stumpPoints!.map((p) => {'x': p.dx, 'y': p.dy}).toList(),
      if (imageSizePx != null) 'imageSizePx': {'width': imageSizePx!.width, 'height': imageSizePx!.height},
      if (imagePointsNorm != null)
        'imagePointsNorm': imagePointsNorm!.map((p) => {'x': p.dx, 'y': p.dy}).toList(),
      if (stumpPointsNorm != null)
        'stumpPointsNorm': stumpPointsNorm!.map((p) => {'x': p.dx, 'y': p.dy}).toList(),
    };
  }

  static List<Offset> _parsePoints(List raw) {
    return raw.map((v) {
      if (v is! Map) throw FormatException('Invalid point');
      final x = v['x'];
      final y = v['y'];
      if (x is! num || y is! num) throw FormatException('Invalid point values');
      return Offset(x.toDouble(), y.toDouble());
    }).toList();
  }

  static PitchCalibration fromJson(Map<String, Object?> json) {
    final raw = json['imagePoints'];
    if (raw is! List) throw FormatException('Expected imagePoints');
    final pts = _parsePoints(raw);
    if (pts.length != 4) throw FormatException('Expected 4 points');

    List<Offset>? stumpPts;
    final stumpRaw = json['stumpPoints'];
    if (stumpRaw is List && stumpRaw.isNotEmpty) {
      stumpPts = _parsePoints(stumpRaw);
    }

    Size? imageSize;
    final sizeRaw = json['imageSizePx'];
    if (sizeRaw is Map) {
      final w = sizeRaw['width'];
      final h = sizeRaw['height'];
      if (w is num && h is num) {
        imageSize = Size(w.toDouble(), h.toDouble());
      }
    }

    List<Offset>? ptsNorm;
    final normRaw = json['imagePointsNorm'];
    if (normRaw is List && normRaw.isNotEmpty) {
      ptsNorm = _parsePoints(normRaw);
    }

    List<Offset>? stumpNorm;
    final stumpNormRaw = json['stumpPointsNorm'];
    if (stumpNormRaw is List && stumpNormRaw.isNotEmpty) {
      stumpNorm = _parsePoints(stumpNormRaw);
    }

    return PitchCalibration(
      imagePoints: pts,
      stumpPoints: stumpPts,
      imageSizePx: imageSize,
      imagePointsNorm: ptsNorm,
      stumpPointsNorm: stumpNorm,
    );
  }
}
