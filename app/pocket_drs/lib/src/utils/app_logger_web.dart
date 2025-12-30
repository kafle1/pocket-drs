import 'package:flutter/foundation.dart';

class AppLogger {
  AppLogger._();

  static final AppLogger instance = AppLogger._();

  Future<void> init() async {}

  void log(String message, {String level = 'INFO'}) {
    final ts = DateTime.now().toIso8601String();
    debugPrint('[$ts] [$level] $message');
  }

  void error(String message, [Object? error, StackTrace? stackTrace]) {
    log(message, level: 'ERROR');
    if (error != null) log('Error: $error', level: 'ERROR');
    if (stackTrace != null) log('Stack: $stackTrace', level: 'ERROR');
  }

  Future<void> dispose() async {}
}