import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';

import 'home_shell.dart';
import 'theme/app_theme.dart';
import 'theme/theme_controller.dart';
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
          title: 'PocketDRS',
          debugShowCheckedModeBanner: false,
          theme: AppTheme.light(),
          darkTheme: AppTheme.dark(),
          themeMode: mode,
          home: StreamBuilder<User?>(
            stream: _auth.authStateChanges,
            builder: (context, snapshot) {
              if (snapshot.connectionState == ConnectionState.waiting) {
                return const Scaffold(
                  body: Center(child: CircularProgressIndicator()),
                );
              }
              
              if (snapshot.hasData) {
                return const HomeShell();
              }
              
              return const LoginScreen();
            },
          ),
        );
      },
    );
  }
}
