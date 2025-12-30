import 'package:flutter/material.dart';
import 'dart:ui';
import 'package:firebase_core/firebase_core.dart';

import 'firebase_options.dart';
import 'src/pocket_drs_app.dart';
import 'src/utils/app_logger.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );
  
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
