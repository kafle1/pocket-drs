import 'package:flutter_test/flutter_test.dart';

import 'package:pocket_drs/src/analysis/lbw_assessor.dart';
import 'package:pocket_drs/src/analysis/lbw_models.dart';

void main() {
  test('LbwAssessor predicts stumps intersection from a straight line', () {
    // World coordinates: x decreases towards stumps at x=0.
    // Here y drifts slightly off-side but stays within wicket band.
    final pts = <PitchPlaneTrackPoint>[];
    for (var i = 0; i < 12; i++) {
      final x = 5.0 - i * 0.4;
      final y = 0.02 + i * 0.001;
      pts.add(
        PitchPlaneTrackPoint(
          tMs: i * 10,
          imagePx: Offset.zero,
          worldM: Offset(x, y),
          confidence: 1,
        ),
      );
    }

    final a = const LbwAssessor().assess(
      points: pts,
      pitchIndex: 3,
      impactIndex: pts.length - 1,
      predictionTailPoints: 6,
    );

    expect(a.predictedAtStumps.dx, 0);
    // Should be close to the line y ~ 0.02 + slope*(x), but evaluated at x=0.
    // We only care that it is finite and near the observed band.
    expect(a.predictedAtStumps.dy.isFinite, true);
    expect(a.wouldHitStumps, true);
  });

  test('LbwAssessor classifies outside line as NOT hitting', () {
    final pts = <PitchPlaneTrackPoint>[];
    for (var i = 0; i < 8; i++) {
      pts.add(
        PitchPlaneTrackPoint(
          tMs: i * 10,
          imagePx: Offset.zero,
          worldM: Offset(4.0 - i * 0.3, 0.6),
          confidence: 1,
        ),
      );
    }

    final a = const LbwAssessor().assess(
      points: pts,
      pitchIndex: 2,
      impactIndex: pts.length - 1,
    );

    expect(a.pitchedInLine, false);
    expect(a.impactInLine, false);
    expect(a.wouldHitStumps, false);
  });
}
