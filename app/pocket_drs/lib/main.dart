import 'package:flutter/material.dart';
import 'dart:ui';

import 'src/pocket_drs_app.dart';
import 'src/utils/analysis_logger.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  // Capture framework errors.
  FlutterError.onError = (details) {
    FlutterError.presentError(details);
    final st = details.stack ?? StackTrace.current;
    AnalysisLogger.instance.logException(details.exception, st, context: 'flutter');
  };

  // Capture async errors that escape the framework.
  PlatformDispatcher.instance.onError = (error, stack) {
    AnalysisLogger.instance.logException(error, stack, context: 'platform');
    return true;
  };

  runApp(const PocketDrsApp());
}
