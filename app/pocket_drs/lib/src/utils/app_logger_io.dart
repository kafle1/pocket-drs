import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

class AppLogger {
  AppLogger._();

  static final AppLogger instance = AppLogger._();

  static const String _logDirOverride = String.fromEnvironment('POCKET_DRS_LOG_DIR');

  IOSink? _sink;
  File? _file;
  bool _ready = false;

  Future<void> init() async {
    if (_ready) return;

    final Directory dir;
    if (_logDirOverride.trim().isNotEmpty) {
      dir = Directory(_logDirOverride.trim());
    } else {
      final base = await getApplicationSupportDirectory();
      dir = Directory('${base.path}/logs/flutter');
    }

    await dir.create(recursive: true);

    final ts = DateTime.now().toIso8601String().replaceAll(':', '-');
    _file = File('${dir.path}/app_$ts.log');
    _sink = _file!.openWrite(mode: FileMode.append);
    _ready = true;
  }

  void log(String message, {String level = 'INFO'}) {
    final ts = DateTime.now().toIso8601String();
    final line = '[$ts] [$level] $message';

    // Console is still useful during dev and CI.
    debugPrint(line);

    if (!_ready || _sink == null) return;
    _sink!.writeln(line);
  }

  void error(String message, [Object? error, StackTrace? stackTrace]) {
    log(message, level: 'ERROR');
    if (error != null) log('Error: $error', level: 'ERROR');
    if (stackTrace != null) log('Stack: $stackTrace', level: 'ERROR');

    // Best-effort flush for crash scenarios.
    try {
      _sink?.flush();
    } catch (_) {
      // ignore
    }
  }

  Future<void> dispose() async {
    final sink = _sink;
    _sink = null;
    _ready = false;
    if (sink == null) return;
    await sink.flush();
    await sink.close();
  }
}