import 'package:flutter_test/flutter_test.dart';

import 'package:pocket_drs/src/utils/app_settings.dart';

void main() {
  test('defaultServerUrl is non-empty', () {
    final url = AppSettings.defaultServerUrl();
    expect(url.trim().isNotEmpty, isTrue);
  });
}
