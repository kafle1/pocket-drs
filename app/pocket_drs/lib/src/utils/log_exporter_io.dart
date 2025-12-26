import 'package:flutter/foundation.dart';

/// Platform-safe log export.
///
/// On mobile, logs are already written to a file; exporting typically means
/// copying/sharing the file path or the content.
///
/// We keep this as a no-op helper so UI code can call the same API across
/// platforms without importing `dart:html`.
Future<void> exportTextFile({
  required String filename,
  required String contents,
}) async {
  debugPrint('exportTextFile($filename): ${contents.length} bytes');
}
