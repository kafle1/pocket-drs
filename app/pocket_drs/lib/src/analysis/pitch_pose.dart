import 'dart:math' as math;
import 'dart:ui';

import 'pitch_calibration.dart';

/// Compact pose description for rendering the calibrated pitch in 3D.
class PitchPose {
  const PitchPose({
    this.yawDeg = 0,
    this.tiltDeg = 0,
    this.rollDeg = 0,
    this.cameraDistanceM = 18,
    this.cameraHeightM = 2.4,
    this.cameraLateralOffsetM = 0,
    this.targetXM = 10.06,
  });

  final double yawDeg;
  final double tiltDeg;
  final double rollDeg;
  final double cameraDistanceM;
  final double cameraHeightM;
  final double cameraLateralOffsetM;
  final double targetXM;

  static const zero = PitchPose();

  Map<String, double> toJson() => <String, double>{
        'yawDeg': yawDeg,
        'tiltDeg': tiltDeg,
        'rollDeg': rollDeg,
      'cameraDistanceM': cameraDistanceM,
      'cameraHeightM': cameraHeightM,
      'cameraLateralOffsetM': cameraLateralOffsetM,
      'targetXM': targetXM,
      };

  @override
  bool operator ==(Object other) {
    return other is PitchPose &&
        other.yawDeg == yawDeg &&
        other.tiltDeg == tiltDeg &&
        other.rollDeg == rollDeg &&
        other.cameraDistanceM == cameraDistanceM &&
        other.cameraHeightM == cameraHeightM &&
        other.cameraLateralOffsetM == cameraLateralOffsetM &&
        other.targetXM == targetXM;
  }

  @override
  int get hashCode => Object.hash(
        yawDeg,
        tiltDeg,
        rollDeg,
        cameraDistanceM,
        cameraHeightM,
        cameraLateralOffsetM,
        targetXM,
      );
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
      cameraDistanceM: _computeCameraDistanceM(corners),
      cameraHeightM: _computeCameraHeightM(corners),
      cameraLateralOffsetM: _computeCameraLateralOffsetM(corners),
      targetXM: _computeTargetXM(corners),
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
    final topEdge = pts[1] - pts[0];
    final bottomEdge = pts[2] - pts[3];
    final topAngle = math.atan2(topEdge.dy, topEdge.dx);
    final bottomAngle = math.atan2(bottomEdge.dy, bottomEdge.dx);
    return _clampDeg(((topAngle + bottomAngle) * 0.5) * _radToDeg, 25);
  }

  static double _computeCameraDistanceM(List<Offset> pts) {
    final nearWidth = (pts[1] - pts[0]).distance;
    final farWidth = (pts[2] - pts[3]).distance;
    if (nearWidth <= 1e-6 || farWidth <= 1e-6) return 18;
    final perspective = (nearWidth / farWidth).clamp(0.6, 4.0);
    final normalized = ((perspective - 1.0) / 3.0).clamp(0.0, 1.0);
    return 22.0 - normalized * 12.0;
  }

  static double _computeCameraHeightM(List<Offset> pts) {
    final nearMid = _mid(pts[0], pts[1]);
    final farMid = _mid(pts[3], pts[2]);
    final span = (farMid.dy - nearMid.dy).abs().clamp(0.05, 0.95);
    final normalized = ((span - 0.15) / 0.55).clamp(0.0, 1.0);
    return 3.4 - normalized * 1.8;
  }

  static double _computeCameraLateralOffsetM(List<Offset> pts) {
    final centerMid = _mid(_mid(pts[0], pts[1]), _mid(pts[3], pts[2]));
    final centerDx = (centerMid.dx - 0.5).clamp(-0.5, 0.5);
    return centerDx * 10.0;
  }

  static double _computeTargetXM(List<Offset> pts) {
    final nearWidth = (pts[1] - pts[0]).distance;
    final farWidth = (pts[2] - pts[3]).distance;
    if (nearWidth <= 1e-6 || farWidth <= 1e-6) return 10.06;
    final perspective = (nearWidth / farWidth).clamp(0.6, 4.0);
    final normalized = ((perspective - 1.0) / 3.0).clamp(0.0, 1.0);
    return 10.06 - normalized * 2.0;
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
