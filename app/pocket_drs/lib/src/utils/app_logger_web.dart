import 'package:flutter/foundation.dart';

class AppLogger {
  AppLogger._();

  static final AppLogger instance = AppLogger._();

  Future<void> init({String? appVersion, String? buildNumber}) async {}

  String? get currentLogFilePath => null;
  String? get currentLogDir => null;

  void log(String message, {String level = 'INFO', String tag = 'app', bool toConsole = true}) {
    final ts = DateTime.now().toIso8601String();
    if (toConsole) {
      debugPrint('[$ts] [$level] [$tag] $message');
    }
  }

  void error(String message, [Object? error, StackTrace? stackTrace, String tag = 'app']) {
    log(message, level: 'ERROR', tag: tag);
    if (error != null) log('Error: $error', level: 'ERROR', tag: tag);
    if (stackTrace != null) log('Stack: $stackTrace', level: 'ERROR', tag: tag);
  }

  Future<void> dispose() async {}
}
