import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';

import 'theme/app_theme.dart';
import 'theme/theme_controller.dart';
import 'screens/analyze_screen.dart';
import 'screens/login_screen.dart';
import 'services/auth_service.dart';

class PocketDrsApp extends StatefulWidget {
  const PocketDrsApp({super.key});

  @override
  State<PocketDrsApp> createState() => _PocketDrsAppState();
}

class _PocketDrsAppState extends State<PocketDrsApp> {
  final _auth = AuthService();

  @override
  void initState() {
    super.initState();
    ThemeController.instance.ensureLoaded();
  }

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<ThemeMode>(
      valueListenable: ThemeController.instance.themeMode,
      builder: (context, mode, _) {
        return MaterialApp(
          title: 'Pocket DRS',
          debugShowCheckedModeBanner: false,
          theme: AppTheme.light(),
          darkTheme: AppTheme.dark(),
          themeMode: mode,
          // Cap text scaling so the broadcast-style fixed-tracking layouts
          // can't overflow under very large system font sizes.
          builder: (context, child) {
            final mq = MediaQuery.of(context);
            return MediaQuery(
              data: mq.copyWith(
                textScaler: mq.textScaler.clamp(maxScaleFactor: 1.3),
              ),
              child: child!,
            );
          },
          home: StreamBuilder<User?>(
            stream: _auth.authStateChanges,
            builder: (context, snapshot) {
              if (snapshot.connectionState == ConnectionState.waiting) {
                return const Scaffold(
                  body: Center(child: CircularProgressIndicator()),
                );
              }

              if (snapshot.hasData) {
                return const AnalyzeScreen();
              }

              return const LoginScreen();
            },
          ),
        );
      },
    );
  }
}
