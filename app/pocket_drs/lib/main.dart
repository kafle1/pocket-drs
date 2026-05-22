import 'package:flutter/material.dart';
import 'dart:ui';
import 'package:firebase_core/firebase_core.dart';
import 'package:cloud_firestore/cloud_firestore.dart';

import 'firebase_options.dart';
import 'src/pocket_drs_app.dart';
import 'src/utils/app_logger.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );

  // Firestore is the single source of truth for pitches/analyses. Its own
  // on-device persistence covers offline reads and queues writes, so deletes
  // survive restarts and reconcile on reconnect without a second local cache.
  FirebaseFirestore.instance.settings = const Settings(
    persistenceEnabled: true,
    cacheSizeBytes: Settings.CACHE_SIZE_UNLIMITED,
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
