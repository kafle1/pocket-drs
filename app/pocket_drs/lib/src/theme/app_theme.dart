import 'package:flutter/cupertino.dart' show CupertinoPageTransitionsBuilder;
import 'package:flutter/material.dart';

import 'app_colors.dart';
import 'app_spacing.dart';

class AppTheme {
  AppTheme._();

  static ThemeData light() => _build(Brightness.light);
  static ThemeData dark() => _build(Brightness.dark);

  // every digit the same width, so a changing number doesn't shift the line
  static TextStyle? tabular(TextStyle? s) =>
      s?.copyWith(fontFeatures: const [FontFeature.tabularFigures()]);

  static ThemeData _build(Brightness brightness) {
    final scheme = AppColors.scheme(brightness);
    final base = Typography.material2021(
      platform: TargetPlatform.android,
    ).englishLike;
    // heavier heads so a glance in the sun finds the title first
    final text = base.copyWith(
      displaySmall: base.displaySmall?.copyWith(
        fontWeight: FontWeight.w700,
        letterSpacing: -0.5,
      ),
      headlineMedium: base.headlineMedium?.copyWith(
        fontWeight: FontWeight.w600,
      ),
      headlineSmall: base.headlineSmall?.copyWith(fontWeight: FontWeight.w600),
      titleLarge: base.titleLarge?.copyWith(fontWeight: FontWeight.w600),
      titleMedium: base.titleMedium?.copyWith(fontWeight: FontWeight.w600),
    );
    RoundedRectangleBorder round(double r) =>
        RoundedRectangleBorder(borderRadius: BorderRadius.circular(r));
    // big enough to hit with a thumb on a tripod in the sun
    final big = ButtonStyle(
      minimumSize: const WidgetStatePropertyAll(Size(64, 52)),
      textStyle: WidgetStatePropertyAll(text.titleMedium),
      shape: WidgetStatePropertyAll(round(AppRadius.lg)),
    );
    final small = ButtonStyle(
      minimumSize: const WidgetStatePropertyAll(Size(48, 48)),
      shape: WidgetStatePropertyAll(round(AppRadius.sm)),
    );
    return ThemeData(
      colorScheme: scheme,
      textTheme: text,
      filledButtonTheme: FilledButtonThemeData(style: big),
      outlinedButtonTheme: OutlinedButtonThemeData(style: big),
      textButtonTheme: TextButtonThemeData(style: small),
      segmentedButtonTheme: SegmentedButtonThemeData(style: small),
      cardTheme: CardThemeData(
        margin: EdgeInsets.zero,
        clipBehavior: Clip.antiAlias,
        shape: round(AppRadius.lg),
      ),
      dialogTheme: DialogThemeData(shape: round(AppRadius.lg)),
      bottomSheetTheme: const BottomSheetThemeData(
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(
            top: Radius.circular(AppRadius.lg),
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
        ),
      ),
      popupMenuTheme: PopupMenuThemeData(shape: round(AppRadius.sm)),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        shape: round(AppRadius.sm),
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(
        linearTrackColor: scheme.surfaceContainerHighest,
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
