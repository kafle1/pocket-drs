import 'dart:math' as math;
import 'dart:ui';

import 'lbw_models.dart';

/// Produces a simple LBW assist from a pitch-plane ball track.
///
/// We deliberately keep this conservative:
/// - We only reason on the *pitch plane* (ground rectangle) using homography.
/// - We extrapolate laterally at the stumps using a linear model y(x) near impact.
///
/// This is not full 3D projectile reconstruction; it is an "aid" that becomes
/// credible when the camera angle is stable and calibration taps are accurate.
class LbwAssessor {
  const LbwAssessor();

  LbwAssessment assess({
    required List<PitchPlaneTrackPoint> points,
    required int pitchIndex,
    required int impactIndex,
    int predictionTailPoints = 10,
  }) {
    if (points.isEmpty) {
      throw ArgumentError('points must not be empty');
    }
    if (pitchIndex < 0 || pitchIndex >= points.length) {
      throw RangeError.range(pitchIndex, 0, points.length - 1, 'pitchIndex');
    }
    if (impactIndex < 0 || impactIndex >= points.length) {
      throw RangeError.range(impactIndex, 0, points.length - 1, 'impactIndex');
    }
    if (impactIndex <= pitchIndex) {
      throw ArgumentError('impactIndex must be > pitchIndex');
    }

    final pitch = points[pitchIndex].worldM;
    final impact = points[impactIndex].worldM;

    // Fit y(x) using the last N points leading up to impact.
    final tailStart = math.max(pitchIndex + 1, impactIndex - predictionTailPoints + 1);
    final tail = points.sublist(tailStart, impactIndex + 1);

    final fit = _fitYOverX(tail.map((p) => p.worldM).toList(growable: false));
    final yAtStumps = fit == null ? impact.dy : (fit.a + fit.b * 0.0);
    final predicted = Offset(0, yAtStumps);

    bool inLineY(double y) {
      final tol = LbwConstants.wicketHalfWidthM + LbwConstants.lineToleranceM;
      return y.abs() <= tol;
    }

    final pitchedInLine = inLineY(pitch.dy);
    final impactInLine = inLineY(impact.dy);
    final wouldHitStumps = inLineY(predicted.dy);

    // Determine wicket decision with umpire's call zone
    LbwDecision wicketDecision;
    final yAbs = predicted.dy.abs();
    final stumpsZone = LbwConstants.wicketHalfWidthM;
    final umpiresCallOuter = stumpsZone + LbwConstants.umpiresCallZoneM;

    if (yAbs <= stumpsZone) {
      wicketDecision = LbwDecision.out;
    } else if (yAbs <= umpiresCallOuter) {
      wicketDecision = LbwDecision.umpiresCall;
    } else {
      wicketDecision = LbwDecision.notOut;
    }

    return LbwAssessment(
      pitchPoint: pitch,
      impactPoint: impact,
      predictedAtStumps: predicted,
      predictionUsedPoints: tail.length,
      pitchedInLine: pitchedInLine,
      impactInLine: impactInLine,
      wouldHitStumps: wouldHitStumps,
      wicketDecision: wicketDecision,
    );
  }
}

class _LineFit {
  const _LineFit({required this.a, required this.b});

  /// y = a + b*x
  final double a;
  final double b;
}

_LineFit? _fitYOverX(List<Offset> pts) {
  // Require enough points for a stable fit.
  if (pts.length < 2) return null;

  // Standard least squares for y = a + b*x.
  var sumX = 0.0;
  var sumY = 0.0;
  var sumXX = 0.0;
  var sumXY = 0.0;
  var n = 0;

  for (final p in pts) {
    final x = p.dx;
    final y = p.dy;
    if (x.isNaN || y.isNaN || x.isInfinite || y.isInfinite) continue;
    n++;
    sumX += x;
    sumY += y;
    sumXX += x * x;
    sumXY += x * y;
  }

  if (n < 2) return null;

  final denom = (n * sumXX - sumX * sumX);
  if (denom.abs() < 1e-9) {
    // Vertical cluster in X; we can't estimate slope reliably.
    return null;
  }

  final b = (n * sumXY - sumX * sumY) / denom;
  final a = (sumY - b * sumX) / n;
  return _LineFit(a: a, b: b);
}
