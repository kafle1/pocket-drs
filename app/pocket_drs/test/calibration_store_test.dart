import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:pocket_drs/src/analysis/calibration_config.dart';
import 'package:pocket_drs/src/utils/calibration_store.dart';

void main() {
  test('CalibrationStore returns defaults when empty', () async {
    SharedPreferences.setMockInitialValues(<String, Object>{});

    final store = CalibrationStore();
    final cfg = await store.loadOrDefault();

    expect(cfg.validate(), isEmpty);
  });

  test('CalibrationStore saves and loads config', () async {
    SharedPreferences.setMockInitialValues(<String, Object>{});

    final store = CalibrationStore();
    const cfg = CalibrationConfig(
      pitchLengthM: 20.12,
      pitchWidthM: 3.05,
      stumpHeightM: 0.711,
      cameraHeightM: 1.6,
      cameraDistanceToStumpsM: 18.0,
      cameraLateralOffsetM: 0.5,
    );

    await store.save(cfg);
    final loaded = await store.loadOrDefault();

    expect(loaded.pitchLengthM, cfg.pitchLengthM);
    expect(loaded.stumpHeightM, cfg.stumpHeightM);
    expect(loaded.cameraHeightM, cfg.cameraHeightM);
    expect(loaded.cameraDistanceToStumpsM, cfg.cameraDistanceToStumpsM);
    expect(loaded.cameraLateralOffsetM, cfg.cameraLateralOffsetM);
  });

  test('CalibrationStore falls back to defaults on bad JSON', () async {
    SharedPreferences.setMockInitialValues(<String, Object>{
      'calibration_config_v1': '{not json',
    });

    final store = CalibrationStore();
    final cfg = await store.loadOrDefault();

    expect(cfg.validate(), isEmpty);
  });
}
