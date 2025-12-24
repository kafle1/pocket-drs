import 'package:shared_preferences/shared_preferences.dart';

class AppSettings {
  static const _kUseBackend = 'useBackend';
  static const _kServerUrl = 'serverUrl';

  static Future<bool> getUseBackend() async {
    final p = await SharedPreferences.getInstance();
    return p.getBool(_kUseBackend) ?? false;
  }

  static Future<void> setUseBackend(bool v) async {
    final p = await SharedPreferences.getInstance();
    await p.setBool(_kUseBackend, v);
  }

  static Future<String> getServerUrl() async {
    final p = await SharedPreferences.getInstance();
    return p.getString(_kServerUrl) ?? '';
  }

  static Future<void> setServerUrl(String v) async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_kServerUrl, v.trim());
  }
}
