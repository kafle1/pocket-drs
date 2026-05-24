import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

enum SpeedUnit {
  kmh('km/h'),
  mph('mph');

  const SpeedUnit(this.label);
  final String label;
}

class AppSettings {
  static const _kServerUrl = 'serverUrl';
  static const _kThemeMode = 'themeMode_v1';
  static const _kSpeedUnit = 'speedUnit_v1';
  static const _kAutoDeleteSource = 'autoDeleteSource_v1';
  static const String _kServerUrlOverride = String.fromEnvironment(
    'POCKET_DRS_SERVER_URL',
    defaultValue: '',
  );

  static String defaultServerUrl() {
    if (_kServerUrlOverride.isNotEmpty) return _kServerUrlOverride;

    // Web runs on the same machine as the backend during development.
    if (kIsWeb) return 'http://localhost:8000';

    // Android emulator reaches host machine via 10.0.2.2.
    if (defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000';
    }

    // iOS simulator can use localhost.
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      return 'http://localhost:8000';
    }

    // Desktop (dev) default.
    return 'http://localhost:8000';
  }

  static Future<String> getServerUrl() async {
    if (_kServerUrlOverride.isNotEmpty) return _kServerUrlOverride;

    try {
      final p = await SharedPreferences.getInstance();
      final stored = p.getString(_kServerUrl);
      final normalized = stored?.trim() ?? '';
      if (normalized.isNotEmpty) return normalized;

      // Persist a safe default so the app never gets into the "URL not set" state.
      final fallback = defaultServerUrl();
      await p.setString(_kServerUrl, fallback);
      return fallback;
    } catch (_) {
      // SharedPreferences can fail in some web contexts (storage disabled).
      // Still return a usable URL so the app can continue.
      return defaultServerUrl();
    }
  }

  static Future<void> setServerUrl(String v) async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_kServerUrl, v.trim());
  }

  static Future<ThemeMode> getThemeMode() async {
    try {
      final p = await SharedPreferences.getInstance();
      final raw = (p.getString(_kThemeMode) ?? 'dark').trim();
      return switch (raw) {
        'light' => ThemeMode.light,
        'dark' => ThemeMode.dark,
        _ => ThemeMode.dark,
      };
    } catch (_) {
      return ThemeMode.dark;
    }
  }

  static Future<bool> probeServerReachable(String url) async {
    try {
      final uri = Uri.parse(url.endsWith('/') ? '${url}healthz' : '$url/healthz');
      final res = await http.get(uri).timeout(const Duration(seconds: 3));
      return res.statusCode < 500;
    } catch (_) {
      return false;
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

  static Future<void> setThemeMode(ThemeMode mode) async {
    final p = await SharedPreferences.getInstance();
    final raw = switch (mode) {
      ThemeMode.light => 'light',
      ThemeMode.dark => 'dark',
      _ => 'system',
    };
    await p.setString(_kThemeMode, raw);
  }
}
