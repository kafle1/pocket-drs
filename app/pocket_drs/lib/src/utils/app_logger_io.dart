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

    final override = _logDirOverride.trim();
    final base = await getApplicationSupportDirectory();
    final defaultDir = Directory('${base.path}/logs/flutter');

    Directory chosenDir = defaultDir;
    if (override.isNotEmpty) {
      // The Makefile injects POCKET_DRS_LOG_DIR as a host path (e.g. /Users/...)
      // which is not writable (or even meaningful) on Android/iOS. Avoid crashing
      // the entire app at startup by ignoring clearly-host-only paths.
      final isClearlyHostPath =
          override.startsWith('/Users/') || override.startsWith('/home/');
      final isAbsolutePosix = override.startsWith('/');
      final isMobile = Platform.isAndroid || Platform.isIOS;

      if (isMobile && isAbsolutePosix && isClearlyHostPath) {
        debugPrint(
          '[AppLogger] Ignoring POCKET_DRS_LOG_DIR="$override" on mobile; using "$defaultDir" instead.',
        );
        chosenDir = defaultDir;
      } else {
        chosenDir = Directory(override);
      }
    }

    // Best-effort init: never crash the whole app because the log directory
    // can't be created.
    try {
      await chosenDir.create(recursive: true);
    } catch (e) {
      debugPrint(
        '[AppLogger] Failed to create log dir "${chosenDir.path}": $e. Falling back to "${defaultDir.path}".',
      );
      try {
        await defaultDir.create(recursive: true);
        chosenDir = defaultDir;
      } catch (e2) {
        debugPrint(
          '[AppLogger] Failed to create fallback log dir "${defaultDir.path}": $e2. File logging disabled.',
        );
        _ready = false;
        return;
      }
    }

    try {
      final ts = DateTime.now().toIso8601String().replaceAll(':', '-');
      _file = File('${chosenDir.path}/app_$ts.log');
      _sink = _file!.openWrite(mode: FileMode.append);
      _ready = true;
    } catch (e) {
      debugPrint('[AppLogger] Failed to open log file: $e. File logging disabled.');
      _file = null;
      _sink = null;
      _ready = false;
    }
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