import 'package:flutter/cupertino.dart' show CupertinoPageTransitionsBuilder;
import 'package:flutter/material.dart';

import 'app_colors.dart';

class AppTheme {
  AppTheme._();

  static ThemeData light() => _build(Brightness.light);
  static ThemeData dark() => _build(Brightness.dark);

  // every digit the same width, so a changing number doesn't shift the line
  static TextStyle? tabular(TextStyle? s) =>
      s?.copyWith(fontFeatures: const [FontFeature.tabularFigures()]);

  static ThemeData _build(Brightness brightness) {
    final scheme = ColorScheme.fromSeed(
      seedColor: AppColors.seed,
      brightness: brightness,
    );
    final text = Typography.material2021(
      platform: TargetPlatform.android,
    ).englishLike;
    // big enough to hit with a thumb on a tripod in the sun
    final big = ButtonStyle(
      minimumSize: const WidgetStatePropertyAll(Size(64, 52)),
      textStyle: WidgetStatePropertyAll(text.titleMedium),
    );
    return ThemeData(
      colorScheme: scheme,
      filledButtonTheme: FilledButtonThemeData(style: big),
      outlinedButtonTheme: OutlinedButtonThemeData(style: big),
      snackBarTheme: const SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
      ),
      pageTransitionsTheme: const PageTransitionsTheme(
        builders: {
          TargetPlatform.android: PredictiveBackPageTransitionsBuilder(),
          TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
        },
      ),
    );
  }
}
