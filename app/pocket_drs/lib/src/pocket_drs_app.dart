import 'package:flutter/material.dart';

import 'screens/pitches_screen.dart';
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
          theme: AppTheme.light(),
          darkTheme: AppTheme.dark(),
          themeMode: mode,
          home: const PitchesScreen(),
        );
      },
    );
  }
}
