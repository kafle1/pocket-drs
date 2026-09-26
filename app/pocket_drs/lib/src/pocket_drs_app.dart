import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'theme/app_theme.dart';
import 'theme/theme_controller.dart';
import 'screens/analyze_screen.dart';
import 'screens/home_screen.dart';

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
          title: 'Pocket DRS',
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
          // no live camera session in a browser, so web keeps the upload flow only
          home: kIsWeb ? const AnalyzeScreen() : const HomeScreen(),
        );
      },
    );
  }
}
