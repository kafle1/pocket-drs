import 'package:flutter/material.dart';

import '../utils/app_settings.dart';

class ThemeController {
  ThemeController._();

  static final ThemeController instance = ThemeController._();

  final ValueNotifier<ThemeMode> themeMode = ValueNotifier<ThemeMode>(ThemeMode.system);

  bool _loaded = false;

  Future<void> ensureLoaded() async {
    if (_loaded) return;
    final mode = await AppSettings.getThemeMode();
    themeMode.value = mode;
    _loaded = true;
  }

  Future<void> setThemeMode(ThemeMode mode) async {
    themeMode.value = mode;
    await AppSettings.setThemeMode(mode);
  }
}
