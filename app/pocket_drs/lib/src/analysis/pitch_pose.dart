import 'dart:math' as math;
import 'dart:ui';

import 'pitch_calibration.dart';

/// Compact pose description for rendering the calibrated pitch in 3D.
class PitchPose {
  const PitchPose({this.yawDeg = 0, this.tiltDeg = 0, this.rollDeg = 0});

  final double yawDeg;
  final double tiltDeg;
  final double rollDeg;

  static const zero = PitchPose();

  Map<String, double> toJson() => <String, double>{
        'yawDeg': yawDeg,
        'tiltDeg': tiltDeg,
        'rollDeg': rollDeg,
      };

  @override
  bool operator ==(Object other) {
    return other is PitchPose &&
        other.yawDeg == yawDeg &&
        other.tiltDeg == tiltDeg &&
        other.rollDeg == rollDeg;
  }

  @override
  int get hashCode => Object.hash(yawDeg, tiltDeg, rollDeg);
}

/// Derives a plausible 3D pose from 2D calibration taps so the preview reflects
/// the user's input instead of a fixed canned pose.
class PitchPoseEstimator {
  static PitchPose fromCalibration(PitchCalibration calibration) {
    final corners = _normalizedCorners(calibration);
    if (corners == null || corners.length != 4) return PitchPose.zero;

    return PitchPose(
      yawDeg: _computeYawDeg(corners),
      tiltDeg: _computeTiltDeg(corners),
      rollDeg: _computeRollDeg(corners),
    );
  }

  static List<Offset>? _normalizedCorners(PitchCalibration calibration) {
    final norm = calibration.imagePointsNorm;
    if (norm != null && norm.length == 4) {
      return List<Offset>.from(norm);
    }

    if (calibration.imagePoints.length == 4 && calibration.imageSizePx != null) {
      final size = calibration.imageSizePx!;
      if (size.width > 0 && size.height > 0) {
        return calibration.imagePoints
            .map((p) => Offset(p.dx / size.width, p.dy / size.height))
            .toList(growable: false);
      }
    }
    return null;
  }

  static double _computeYawDeg(List<Offset> pts) {
    final topMid = _mid(pts[0], pts[1]);
    final bottomMid = _mid(pts[3], pts[2]);
    final dx = bottomMid.dx - topMid.dx;
    final dy = bottomMid.dy - topMid.dy;
    // Screen coordinates have y increasing downwards; flip the signed angle so
    // a clockwise rotation (pitch vanishing point moving left) yields positive
    // yaw for an intuitive heading.
    return _clampDeg(-math.atan2(dx, dy) * _radToDeg, 80);
  }

  static double _computeTiltDeg(List<Offset> pts) {
    final topLen = (pts[1] - pts[0]).distance;
    final bottomLen = (pts[2] - pts[3]).distance;
    if (topLen <= 1e-6 || bottomLen <= 1e-6) return 0;
    final ratio = ((bottomLen - topLen) / (topLen + bottomLen)).clamp(-1.0, 1.0);
    return _clampDeg(math.atan(ratio * 1.6) * _radToDeg, 35);
  }

  static double _computeRollDeg(List<Offset> pts) {
    final leftLen = (pts[3] - pts[0]).distance;
    final rightLen = (pts[2] - pts[1]).distance;
    if (leftLen <= 1e-6 || rightLen <= 1e-6) return 0;
    final ratio = ((rightLen - leftLen) / (leftLen + rightLen)).clamp(-1.0, 1.0);
    return _clampDeg(math.atan(ratio * 1.6) * _radToDeg, 30);
  }

  static Offset _mid(Offset a, Offset b) => Offset((a.dx + b.dx) * 0.5, (a.dy + b.dy) * 0.5);

  static double _clampDeg(double value, double maxAbs) {
    if (!value.isFinite) return 0;
    final limit = maxAbs.abs();
    if (value > limit) return limit;
    if (value < -limit) return -limit;
    return value;
  }

  static const double _radToDeg = 180.0 / math.pi;
}
