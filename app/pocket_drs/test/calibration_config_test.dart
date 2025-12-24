import 'package:flutter_test/flutter_test.dart';
import 'package:pocket_drs/src/analysis/calibration_config.dart';

void main() {
  test('CalibrationConfig defaults are valid', () {
    final cfg = CalibrationConfig.defaults();
    expect(cfg.validate(), isEmpty);
  });

  test('CalibrationConfig round-trips JSON', () {
    const cfg = CalibrationConfig(
      pitchLengthM: 20.12,
      pitchWidthM: 3.05,
      stumpHeightM: 0.711,
      cameraHeightM: 1.7,
      cameraDistanceToStumpsM: 17.5,
      cameraLateralOffsetM: -1.0,
    );

    final json = cfg.toJson();
    final decoded = CalibrationConfig.fromJson(json);

    expect(decoded.pitchLengthM, cfg.pitchLengthM);
    expect(decoded.stumpHeightM, cfg.stumpHeightM);
    expect(decoded.cameraHeightM, cfg.cameraHeightM);
    expect(decoded.cameraDistanceToStumpsM, cfg.cameraDistanceToStumpsM);
    expect(decoded.cameraLateralOffsetM, cfg.cameraLateralOffsetM);
  });

  test('CalibrationConfig validate catches out-of-range values', () {
    const cfg = CalibrationConfig(
      pitchLengthM: -1,
      pitchWidthM: -1,
      stumpHeightM: 99,
      cameraHeightM: 0,
      cameraDistanceToStumpsM: 999,
      cameraLateralOffsetM: 999,
    );

    final errors = cfg.validate();
    expect(errors, isNotEmpty);
  });
}
