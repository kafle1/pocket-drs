import 'dart:ui';

import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';

import 'src/account/account.dart';
import 'src/pocket_drs_app.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  PlatformDispatcher.instance.onError = (error, stack) {
    debugPrint('Platform error: $error\n$stack');
    return true;
  };

  try {
    await Firebase.initializeApp();
    await Account.instance.init();
  } catch (e, st) {
    debugPrint('Firebase init failed: $e\n$st');
  }

  runApp(const PocketDrsApp());
}
