import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'src/account/account.dart';
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

  // android reads its firebase settings from google-services.json; web has none here
  if (!kIsWeb) {
    try {
      await Firebase.initializeApp();
      await Account.instance.init();
    } catch (e, st) {
      AppLogger.instance.error('Firebase init failed', e, st);
    }
  }

  runApp(const PocketDrsApp());
}
