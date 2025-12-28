// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;

import 'package:flutter/foundation.dart';

/// Web/desktop-friendly logger.
///
/// On Web there is no writable local filesystem in the same way as mobile.
/// We log to console and keep a copy in browser storage so it can be exported.
class AnalysisLogger {
  AnalysisLogger._();

  static final AnalysisLogger instance = AnalysisLogger._();

  static const _storageKey = 'pocket_drs_analysis_log_v1';

  void _appendToStorage(String line) {
    try {
      final prev = html.window.localStorage[_storageKey] ?? '';
      // Keep it simple: append. (If this ever grows too big, we can rotate.)
      html.window.localStorage[_storageKey] = '$prev$line';
    } catch (_) {
      // Storage is best-effort. In private mode or restrictive browsers this can fail.
    }
  }

  Future<void> log(String message) async {
    // Keep console output readable and consistent.
    debugPrint('[PocketDRS] $message');
    final ts = DateTime.now().toIso8601String();
    _appendToStorage('[$ts] $message\n');
  }

  Future<void> logAndPrint(String message) async {
    await log(message);
  }

  Future<void> logException(
    Object error,
    StackTrace stack, {
    String context = 'uncaught',
  }) async {
    await log('$context error=$error');
    await log(stack.toString());
  }

  Future<void> clear() async {
    try {
      html.window.localStorage.remove(_storageKey);
    } catch (_) {}
  }

  Future<String> readAll() async {
    try {
      return html.window.localStorage[_storageKey] ?? '';
    } catch (_) {
      return '';
    }
  }

  Future<String?> logPath() async => 'browser://localStorage/$_storageKey';
}
