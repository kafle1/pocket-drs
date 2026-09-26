import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

enum SpeedUnit {
  kmh('km/h'),
  mph('mph');

  const SpeedUnit(this.label);
  final String label;
}

class AppSettings {
  static const _kThemeMode = 'themeMode_v1';
  static const _kSpeedUnit = 'speedUnit_v1';
  static const _kAutoDeleteSource = 'autoDeleteSource_v1';
  static const _kPitchLength = 'pitchLength_v1';

  static const fullPitchM = 20.12;
  static const minPitchM = 10.0;
  static const maxPitchM = 25.0;

  static Future<ThemeMode> getThemeMode() async {
    try {
      final p = await SharedPreferences.getInstance();
      return switch (p.getString(_kThemeMode)) {
        'light' => ThemeMode.light,
        'dark' => ThemeMode.dark,
        _ => ThemeMode.system,
      };
    } catch (_) {
      return ThemeMode.system;
    }
  }

  static Future<SpeedUnit> getSpeedUnit() async {
    try {
      final p = await SharedPreferences.getInstance();
      final raw = (p.getString(_kSpeedUnit) ?? 'kmh').trim();
      return raw == 'mph' ? SpeedUnit.mph : SpeedUnit.kmh;
    } catch (_) {
      return SpeedUnit.kmh;
    }
  }

  static Future<void> setSpeedUnit(SpeedUnit unit) async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_kSpeedUnit, unit == SpeedUnit.mph ? 'mph' : 'kmh');
  }

  static Future<bool> getAutoDeleteSource() async {
    try {
      final p = await SharedPreferences.getInstance();
      return p.getBool(_kAutoDeleteSource) ?? false;
    } catch (_) {
      return false;
    }
  }

  static Future<void> setAutoDeleteSource(bool value) async {
    final p = await SharedPreferences.getInstance();
    await p.setBool(_kAutoDeleteSource, value);
  }

  static Future<double> getPitchLength() async {
    try {
      final p = await SharedPreferences.getInstance();
      final v = p.getDouble(_kPitchLength) ?? fullPitchM;
      return v >= minPitchM && v <= maxPitchM ? v : fullPitchM;
    } catch (_) {
      return fullPitchM;
    }
  }

  static Future<void> setPitchLength(double metres) async {
    final p = await SharedPreferences.getInstance();
    await p.setDouble(_kPitchLength, metres);
  }

  static Future<void> setThemeMode(ThemeMode mode) async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_kThemeMode, mode.name);
  }
}
