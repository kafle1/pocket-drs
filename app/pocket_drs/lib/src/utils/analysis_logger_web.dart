import 'package:flutter/foundation.dart';

/// Web/desktop-friendly logger.
///
/// On Web there is no writable local filesystem in the same way as mobile.
/// We log to console only.
class AnalysisLogger {
  AnalysisLogger._();

  static final AnalysisLogger instance = AnalysisLogger._();

  Future<void> log(String message) async {
    // Keep console output readable and consistent.
    debugPrint('[PocketDRS] $message');
  }

  Future<void> logAndPrint(String message) async {
    debugPrint('[PocketDRS] $message');
  }

  Future<void> logException(
    Object error,
    StackTrace stack, {
    String context = 'uncaught',
  }) async {
    debugPrint('[PocketDRS] $context error=$error');
    debugPrint(stack.toString());
  }

  Future<void> clear() async {}

  Future<String> readAll() async => '';

  Future<String?> logPath() async => null;
}
