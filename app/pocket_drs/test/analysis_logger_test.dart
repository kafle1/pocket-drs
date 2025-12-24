import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:path_provider_platform_interface/path_provider_platform_interface.dart';
import 'package:pocket_drs/src/utils/analysis_logger.dart';

class _FakePathProvider extends PathProviderPlatform {
  Directory? _dir;

  @override
  Future<String?> getApplicationDocumentsPath() async {
    _dir ??= await Directory.systemTemp.createTemp('analysis_logger_test');
    return _dir!.path;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('analysis logger writes to file', () async {
    PathProviderPlatform.instance = _FakePathProvider();

    final logger = AnalysisLogger.instance;
    await logger.clear();
    await logger.log('hello world');

    final path = await logger.logPath();
    expect(path, isNotNull);

    final file = File(path!);
    expect(await file.exists(), isTrue);
    final contents = await file.readAsString();
    expect(contents.contains('hello world'), isTrue);
  });
}
