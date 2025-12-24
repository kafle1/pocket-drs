import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../analysis/calibration_config.dart';

class CalibrationStore {
  CalibrationStore({SharedPreferences? prefs}) : _prefs = prefs;

  static const _key = 'calibration_config_v1';

  final SharedPreferences? _prefs;

  Future<SharedPreferences> _getPrefs() async {
    return _prefs ?? SharedPreferences.getInstance();
  }

  Future<CalibrationConfig> loadOrDefault() async {
    final prefs = await _getPrefs();
    final raw = prefs.getString(_key);
    if (raw == null || raw.isEmpty) return CalibrationConfig.defaults();

    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, Object?>) {
        return CalibrationConfig.defaults();
      }
      final cfg = CalibrationConfig.fromJson(decoded);
      return cfg.validate().isEmpty ? cfg : CalibrationConfig.defaults();
    } catch (_) {
      return CalibrationConfig.defaults();
    }
  }

  Future<void> save(CalibrationConfig config) async {
    final errors = config.validate();
    if (errors.isNotEmpty) {
      throw StateError('Invalid calibration config: ${errors.join(', ')}');
    }

    final prefs = await _getPrefs();
    final raw = jsonEncode(config.toJson());
    await prefs.setString(_key, raw);
  }

  Future<void> clear() async {
    final prefs = await _getPrefs();
    await prefs.remove(_key);
  }
}
