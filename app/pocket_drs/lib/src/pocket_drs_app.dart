import 'dart:async';

import 'package:flutter/material.dart';

import 'account/account.dart';
import 'theme/app_theme.dart';
import 'theme/theme_controller.dart';
import 'screens/home_screen.dart';
import 'screens/sign_in_screen.dart';

class PocketDrsApp extends StatefulWidget {
  const PocketDrsApp({super.key});

  @override
  State<PocketDrsApp> createState() => _PocketDrsAppState();
}

class _PocketDrsAppState extends State<PocketDrsApp> {
  final _nav = GlobalKey<NavigatorState>();
  // premium given while the app sat in the background shows up on return
  late final AppLifecycleListener _life;

  @override
  void initState() {
    super.initState();
    ThemeController.instance.ensureLoaded();
    Account.instance.signedIn.addListener(_onSignedIn);
    _life = AppLifecycleListener(
      onResume: () => unawaited(Account.instance.refreshMe()),
    );
  }

  @override
  void dispose() {
    Account.instance.signedIn.removeListener(_onSignedIn);
    _life.dispose();
    super.dispose();
  }

  // signing out mid-flow drops every open screen back to the sign-in gate
  void _onSignedIn() {
    if (!Account.instance.signedIn.value) {
      _nav.currentState?.popUntil((r) => r.isFirst);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<ThemeMode>(
      valueListenable: ThemeController.instance.themeMode,
      builder: (context, mode, _) {
        return MaterialApp(
          title: 'Pocket DRS',
          navigatorKey: _nav,
          debugShowCheckedModeBanner: false,
          theme: AppTheme.light(),
          darkTheme: AppTheme.dark(),
          themeMode: mode,
          // the video screens have fixed-height panels that overflow past 1.3x text
          builder: (context, child) {
            final mq = MediaQuery.of(context);
            return MediaQuery(
              data: mq.copyWith(
                textScaler: mq.textScaler.clamp(maxScaleFactor: 1.3),
              ),
              child: child!,
            );
          },
          home: ValueListenableBuilder<bool>(
            valueListenable: Account.instance.signedIn,
            builder: (context, signedIn, _) =>
                signedIn ? const HomeScreen() : const SignInScreen(),
          ),
        );
      },
    );
  }
}
