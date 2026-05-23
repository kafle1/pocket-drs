import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

class AppLogger {
  AppLogger._();

  static final AppLogger instance = AppLogger._();

  static const String _logDirOverride = String.fromEnvironment('POCKET_DRS_LOG_DIR');
  static const bool _echoInfoToConsole = bool.fromEnvironment('POCKET_DRS_VERBOSE_CONSOLE', defaultValue: false);

  // Rotation policy: cap each file, keep last N for postmortem.
  static const int _maxBytesPerFile = 5 * 1024 * 1024; // 5 MB
  static const int _maxRetained = 8; // sliding window of recent runs

  IOSink? _sink;
  File? _file;
  Directory? _dir;
  bool _ready = false;
  int _bytesWritten = 0;

  Future<void> init({String? appVersion, String? buildNumber}) async {
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

    _dir = chosenDir;

    try {
      final ts = DateTime.now().toIso8601String().replaceAll(':', '-');
      _file = File('${chosenDir.path}/app_$ts.log');
      _sink = _file!.openWrite(mode: FileMode.append);
      _bytesWritten = await _file!.length();
      _ready = true;
    } catch (e) {
      debugPrint('[AppLogger] Failed to open log file: $e. File logging disabled.');
      _file = null;
      _sink = null;
      _ready = false;
      return;
    }

    // Retention: drop oldest files past the sliding window.
    unawaited(_pruneOldFiles());

    // Banner gives every log file enough context to be triaged in isolation.
    final mode = kDebugMode ? 'debug' : (kProfileMode ? 'profile' : 'release');
    final platform = '${Platform.operatingSystem} ${Platform.operatingSystemVersion}';
    final version = (appVersion != null && buildNumber != null)
        ? '$appVersion+$buildNumber'
        : (appVersion ?? 'unknown');
    log('=== session start ===', level: 'INFO', tag: 'boot');
    log('app=$version mode=$mode dart=${Platform.version}', level: 'INFO', tag: 'boot');
    log('platform=$platform locale=${Platform.localeName}', level: 'INFO', tag: 'boot');
    log('log_file=${_file!.path}', level: 'INFO', tag: 'boot');
  }

  String? get currentLogFilePath => _file?.path;
  String? get currentLogDir => _dir?.path;

  void log(String message, {String level = 'INFO', String tag = 'app', bool toConsole = false}) {
    final ts = DateTime.now().toIso8601String();
    final line = '[$ts] [$level] [$tag] $message';

    final isConsoleLevel = level == 'ERROR' || level == 'WARN';
    if (toConsole || isConsoleLevel || (_echoInfoToConsole && kDebugMode)) {
      debugPrint(line);
    }

    if (!_ready || _sink == null) return;
    _sink!.writeln(line);
    _bytesWritten += line.length + 1;

    if (_bytesWritten >= _maxBytesPerFile) {
      // Rotate inline — keeps subsequent writes within the size cap.
      unawaited(_rotate());
    }
  }

  void error(String message, [Object? error, StackTrace? stackTrace, String tag = 'app']) {
    log(message, level: 'ERROR', tag: tag, toConsole: true);
    if (error != null) log('Error: $error', level: 'ERROR', tag: tag, toConsole: true);
    if (stackTrace != null) log('Stack: $stackTrace', level: 'ERROR', tag: tag, toConsole: true);

    // Best-effort flush for crash scenarios.
    try {
      _sink?.flush();
    } catch (_) {
      // ignore
    }
  }

  Future<void> _rotate() async {
    final dir = _dir;
    if (dir == null) return;
    try {
      await _sink?.flush();
      await _sink?.close();
    } catch (_) {
      // ignore
    }
    try {
      final ts = DateTime.now().toIso8601String().replaceAll(':', '-');
      _file = File('${dir.path}/app_$ts.log');
      _sink = _file!.openWrite(mode: FileMode.append);
      _bytesWritten = 0;
    } catch (e) {
      debugPrint('[AppLogger] Rotation failed: $e. File logging disabled.');
      _ready = false;
      _sink = null;
      _file = null;
      return;
    }
    unawaited(_pruneOldFiles());
  }

  Future<void> _pruneOldFiles() async {
    final dir = _dir;
    if (dir == null) return;
    try {
      final entries = await dir
          .list(followLinks: false)
          .where((e) => e is File && e.path.contains('/app_') && e.path.endsWith('.log'))
          .cast<File>()
          .toList();
      if (entries.length <= _maxRetained) return;
      entries.sort((a, b) => a.path.compareTo(b.path)); // ts-sortable filenames
      final toDelete = entries.length - _maxRetained;
      for (var i = 0; i < toDelete; i++) {
        try {
          await entries[i].delete();
        } catch (_) {
          // ignore individual failures
        }
      }
    } catch (_) {
      // ignore: retention is best-effort
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
