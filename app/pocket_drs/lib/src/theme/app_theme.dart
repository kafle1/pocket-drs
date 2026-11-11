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

  // the small capitals over a tile, the way the 3D replay labels its rows
  static TextStyle? caps(TextStyle? s) =>
      s?.copyWith(fontWeight: FontWeight.w700, letterSpacing: 1.1);

  static ThemeData _build(Brightness brightness) {
    final scheme = AppColors.scheme(brightness);
    // englishLike alone carries sizes but no colours, which left plain headings white on the light theme
    final base = ThemeData(
      colorScheme: scheme,
      platform: TargetPlatform.android,
    ).textTheme;
    TextStyle? w(TextStyle? s, FontWeight weight, [double? spacing]) =>
        s?.copyWith(fontWeight: weight, letterSpacing: spacing);
    // heavy heads and quiet body, so a glance in the sun finds the call first
    final text = base.copyWith(
      displayMedium: w(base.displayMedium, FontWeight.w800, -1.2),
      displaySmall: w(base.displaySmall, FontWeight.w800, -0.8),
      headlineMedium: w(base.headlineMedium, FontWeight.w700, -0.4),
      headlineSmall: w(base.headlineSmall, FontWeight.w700, -0.2),
      titleLarge: w(base.titleLarge, FontWeight.w700),
      titleMedium: w(base.titleMedium, FontWeight.w600),
      titleSmall: w(base.titleSmall, FontWeight.w600),
      labelLarge: w(base.labelLarge, FontWeight.w600),
    );
    final shape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(AppRadius.lg),
    );
    final small = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(AppRadius.sm),
    );
    // big enough to hit with a thumb on a tripod in the sun
    final big = ButtonStyle(
      minimumSize: const WidgetStatePropertyAll(Size(64, 52)),
      textStyle: WidgetStatePropertyAll(text.titleMedium),
      shape: WidgetStatePropertyAll(shape),
    );
    return ThemeData(
      colorScheme: scheme,
      textTheme: text,
      scaffoldBackgroundColor: scheme.surface,
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surface,
        surfaceTintColor: Colors.transparent,
        titleTextStyle: text.titleLarge?.copyWith(color: scheme.onSurface),
      ),
      filledButtonTheme: FilledButtonThemeData(style: big),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: big.copyWith(
          side: WidgetStatePropertyAll(BorderSide(color: scheme.outline)),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: ButtonStyle(
          minimumSize: const WidgetStatePropertyAll(Size(48, 48)),
          shape: WidgetStatePropertyAll(small),
        ),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: ButtonStyle(shape: WidgetStatePropertyAll(small)),
      ),
      segmentedButtonTheme: SegmentedButtonThemeData(
        style: ButtonStyle(
          minimumSize: const WidgetStatePropertyAll(Size(48, 48)),
          shape: WidgetStatePropertyAll(small),
        ),
      ),
      cardTheme: CardThemeData(
        margin: EdgeInsets.zero,
        elevation: 0,
        color: scheme.surfaceContainerLowest,
        clipBehavior: Clip.antiAlias,
        shape: shape,
      ),
      listTileTheme: const ListTileThemeData(
        contentPadding: EdgeInsets.symmetric(horizontal: AppSpacing.lg),
      ),
      chipTheme: ChipThemeData(shape: small, side: BorderSide.none),
      dialogTheme: DialogThemeData(shape: shape),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: scheme.surfaceContainerLow,
        shape: const RoundedRectangleBorder(
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
      popupMenuTheme: PopupMenuThemeData(shape: small),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        shape: small,
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(
        linearTrackColor: scheme.surfaceContainerHighest,
      ),
      dividerTheme: DividerThemeData(color: scheme.outlineVariant, space: 1),
      pageTransitionsTheme: const PageTransitionsTheme(
        builders: {
          TargetPlatform.android: PredictiveBackPageTransitionsBuilder(),
          TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
        },
      ),
    );
  }
}
