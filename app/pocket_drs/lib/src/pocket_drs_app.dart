import 'package:flutter/material.dart';

import 'home_shell.dart';
import 'theme/app_theme.dart';
import 'theme/theme_controller.dart';

class PocketDrsApp extends StatefulWidget {
  const PocketDrsApp({super.key});

  @override
  State<PocketDrsApp> createState() => _PocketDrsAppState();
}

class _PocketDrsAppState extends State<PocketDrsApp> {
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
          home: const HomeShell(),
        );
      },
    );
  }
}
