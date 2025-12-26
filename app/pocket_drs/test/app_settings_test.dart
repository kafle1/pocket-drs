import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:pocket_drs/src/utils/app_settings.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  tearDown(() {
    debugDefaultTargetPlatformOverride = null;
  });

  test('getServerUrl returns a non-empty default and persists it', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;

    final url1 = await AppSettings.getServerUrl();
    expect(url1, isNotEmpty);

    final url2 = await AppSettings.getServerUrl();
    expect(url2, url1);
  });

  test('default server URL uses Android emulator host when on Android', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;

    final url = await AppSettings.getServerUrl();
    expect(url, 'http://10.0.2.2:8000');
  });

  test('default server URL uses localhost when on iOS', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;

    final url = await AppSettings.getServerUrl();
    expect(url, 'http://localhost:8000');
  });

  test('defaultServerUrl is never empty', () {
    expect(AppSettings.defaultServerUrl(), isNotEmpty);
  });
}
