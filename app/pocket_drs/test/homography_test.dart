import 'package:flutter_test/flutter_test.dart';
import 'package:pocket_drs/src/analysis/pitch_calibration.dart';

void main() {
  test('PitchCalibration.validateImageQuad accepts a convex quad', () {
    final cal = PitchCalibration(
      imagePoints: const [
        Offset(0, 0),
        Offset(100, 0),
        Offset(110, 50),
        Offset(10, 50),
      ],
    );

    expect(cal.validateImageQuad, returnsNormally);
  });

  test('PitchCalibration.validateImageQuad rejects collinear taps', () {
    final cal = PitchCalibration(
      imagePoints: const [
        Offset(0, 0),
        Offset(1, 0),
        Offset(2, 0),
        Offset(3, 0),
      ],
    );

    expect(cal.validateImageQuad, throwsA(isA<StateError>()));
  });
}
