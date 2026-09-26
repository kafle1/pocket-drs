import 'package:flutter/material.dart';
import 'dart:ui';

import 'src/pocket_drs_app.dart';
import 'src/utils/app_logger.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  await AppLogger.instance.init();

  FlutterError.onError = (details) {
    FlutterError.presentError(details);
    AppLogger.instance.error(
      'Flutter error',
      details.exception,
      details.stack ?? StackTrace.current,
    );
  };

  PlatformDispatcher.instance.onError = (error, stack) {
    AppLogger.instance.error('Platform error', error, stack);
    return true;
  };

  runApp(const PocketDrsApp());
}
