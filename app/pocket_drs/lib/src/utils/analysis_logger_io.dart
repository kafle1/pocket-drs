import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

/// Lightweight file logger for analysis runs.
///
/// Only used on mobile (no-ops on web/desktop) and appends to
/// `<documents>/analysis_log.txt` so users can share logs without
/// capturing full logcat.
class AnalysisLogger {
  AnalysisLogger._();

  static final AnalysisLogger instance = AnalysisLogger._();

  File? _file;

  Future<File?> _ensureFile() async {
    final inTest = Platform.environment['FLUTTER_TEST'] == 'true';
    if (kIsWeb || (!inTest && !Platform.isAndroid && !Platform.isIOS)) {
      return null;
    }
    if (_file != null) return _file;

    try {
      final dir = await getApplicationDocumentsDirectory();
      final file = File('${dir.path}/analysis_log.txt');
      _file = file;
      return file;
    } catch (_) {
      return null;
    }
  }

  Future<void> log(String message) async {
    final file = await _ensureFile();
    if (file == null) return;
    final ts = DateTime.now().toIso8601String();
    final line = '[$ts] $message\n';
    await file.writeAsString(line, mode: FileMode.append, flush: true);
  }

  Future<void> logAndPrint(String message) async {
    await log(message);
  }

  Future<void> logException(
    Object error,
    StackTrace stack, {
    String context = 'uncaught',
  }) async {
    await logAndPrint('$context error=$error');
    // Stack traces can be large; still capture them because you asked for detailed logs.
    await log(stack.toString());
  }

  Future<void> clear() async {
    final file = await _ensureFile();
    if (file == null) return;
    if (await file.exists()) {
      await file.writeAsString('');
    }
  }

  Future<String> readAll() async {
    final file = await _ensureFile();
    if (file == null) return '';
    if (!await file.exists()) return '';
    return file.readAsString();
  }

  Future<String?> logPath() async {
    final file = await _ensureFile();
    return file?.path;
  }
}
