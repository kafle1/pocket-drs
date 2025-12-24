import 'dart:ui';

/// Cricket-law-ish constants used for a lightweight LBW assist.
///
/// This project is a student prototype, not a certified DRS replacement.
/// We keep the model simple, explicit, and editable.
class LbwConstants {
  /// Total wicket width (outer edge of off stump to outer edge of leg stump).
  /// 9 inches = 0.2286m.
  static const double wicketWidthM = 0.2286;

  static double get wicketHalfWidthM => wicketWidthM / 2.0;

  /// Approx cricket ball radius.
  /// A standard ball diameter is ~72mm -> radius ~36mm.
  static const double ballRadiusM = 0.036;

  /// How much extra lateral tolerance we allow when classifying "in line".
  static const double lineToleranceM = ballRadiusM;

  /// Umpire's call zone extends slightly beyond stumps (half ball width).
  /// If the ball clips the edge, it's "umpire's call".
  static const double umpiresCallZoneM = ballRadiusM;
}

/// Decision category for LBW
enum LbwDecision {
  out,
  notOut,
  umpiresCall,
}

class PitchPlaneTrackPoint {
  const PitchPlaneTrackPoint({
    required this.tMs,
    required this.imagePx,
    required this.worldM,
    required this.confidence,
  });

  final int tMs;
  final Offset imagePx;

  /// Pitch-plane coordinates in meters.
  ///
  /// Convention matches [PitchCalibration.homography]: origin at striker stumps,
  /// X increases towards bowler end, Y is lateral (negative = left, positive = right).
  final Offset worldM;

  final double confidence;
}

class LbwAssessment {
  const LbwAssessment({
    required this.pitchPoint,
    required this.impactPoint,
    required this.predictedAtStumps,
    required this.predictionUsedPoints,
    required this.pitchedInLine,
    required this.impactInLine,
    required this.wouldHitStumps,
    required this.wicketDecision,
  });

  final Offset pitchPoint;
  final Offset impactPoint;
  final Offset predictedAtStumps;
  final int predictionUsedPoints;
  final bool pitchedInLine;
  final bool impactInLine;
  final bool wouldHitStumps;
  
  /// More nuanced decision considering umpire's call zone.
  final LbwDecision wicketDecision;

  /// Overall decision string.
  String get decisionText {
    if (!pitchedInLine) return 'NOT OUT - Pitched outside leg';
    if (!impactInLine) return 'NOT OUT - Impact outside line';
    switch (wicketDecision) {
      case LbwDecision.out:
        return 'OUT';
      case LbwDecision.notOut:
        return 'NOT OUT - Missing stumps';
      case LbwDecision.umpiresCall:
        return "UMPIRE'S CALL - Clipping stumps";
    }
  }
}
