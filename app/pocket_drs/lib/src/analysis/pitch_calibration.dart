import 'dart:ui';

import 'homography.dart';

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

  Homography homography({required double pitchLengthM, required double pitchWidthM}) {
    if (imagePoints.length != 4) {
      throw StateError('PitchCalibration requires 4 image points');
    }

    // World coordinates on pitch plane (meters). Origin at striker stumps,
    // X increases towards bowler stumps.
    final halfW = pitchWidthM / 2.0;
    final dst = <Offset>[
      Offset(0, -halfW),
      Offset(0, halfW),
      Offset(pitchLengthM, halfW),
      Offset(pitchLengthM, -halfW),
    ];

    return Homography.fromFourPoints(src: imagePoints, dst: dst);
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
