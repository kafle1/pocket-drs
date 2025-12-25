import 'package:shared_preferences/shared_preferences.dart';

class AppSettings {
  static const _kServerUrl = 'serverUrl';

  static Future<String> getServerUrl() async {
    final p = await SharedPreferences.getInstance();
    return p.getString(_kServerUrl) ?? '';
  }

  static Future<void> setServerUrl(String v) async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_kServerUrl, v.trim());
  }
}
