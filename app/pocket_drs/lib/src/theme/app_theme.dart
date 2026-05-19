import 'package:flutter/material.dart';

import 'app_colors.dart';
import 'app_spacing.dart';
import 'app_typography.dart';

/// DRS Telemetry theme — sharp-cornered broadcast HUD aesthetic.
/// Single accent (cricket signal red), ink-black surfaces, hairline borders,
/// tabular monospace numerics, all-caps stencil labels.
class AppTheme {
  AppTheme._();

  static ThemeData dark() {
    const onSurface = AppColors.bone;
    const scheme = ColorScheme.dark(
      primary: AppColors.bone,
      onPrimary: AppColors.inkBlack,
      secondary: AppColors.signalRed,
      onSecondary: AppColors.bone,
      tertiary: AppColors.pitchGreen,
      onTertiary: AppColors.inkBlack,
      error: AppColors.signalRed,
      onError: AppColors.bone,
      surface: AppColors.inkBlack,
      onSurface: onSurface,
      surfaceContainerLowest: AppColors.inkBlack,
      surfaceContainerLow: AppColors.carbon,
      surfaceContainer: AppColors.carbon,
      surfaceContainerHigh: AppColors.graphite,
      surfaceContainerHighest: AppColors.slate,
      onSurfaceVariant: AppColors.ash,
      outline: AppColors.hairlineDark,
      outlineVariant: AppColors.hairlineDark,
      primaryContainer: AppColors.graphite,
      onPrimaryContainer: AppColors.bone,
      secondaryContainer: Color(0xFF2A0E12),
      onSecondaryContainer: AppColors.signalRed,
      tertiaryContainer: Color(0xFF06241A),
      onTertiaryContainer: AppColors.pitchGreen,
      errorContainer: Color(0xFF2A0E12),
      onErrorContainer: AppColors.signalRed,
    );
    return _build(scheme, true);
  }

  static ThemeData light() {
    const onSurface = AppColors.ink;
    const scheme = ColorScheme.light(
      primary: AppColors.ink,
      onPrimary: AppColors.paper,
      secondary: AppColors.signalRedDeep,
      onSecondary: AppColors.paper,
      tertiary: AppColors.pitchGreenDeep,
      onTertiary: AppColors.paper,
      error: AppColors.signalRedDeep,
      onError: AppColors.paper,
      surface: AppColors.paper,
      onSurface: onSurface,
      surfaceContainerLowest: AppColors.paper,
      surfaceContainerLow: AppColors.paperSurface,
      surfaceContainer: AppColors.paperSurface,
      surfaceContainerHigh: AppColors.paperRaised,
      surfaceContainerHighest: Color(0xFFE8E8E2),
      onSurfaceVariant: AppColors.inkMuted,
      outline: AppColors.hairlineLight,
      outlineVariant: AppColors.hairlineLight,
      primaryContainer: AppColors.paperRaised,
      onPrimaryContainer: AppColors.ink,
      secondaryContainer: Color(0xFFFEE5E7),
      onSecondaryContainer: AppColors.signalRedDeep,
      tertiaryContainer: Color(0xFFD9F5E5),
      onTertiaryContainer: AppColors.pitchGreenDeep,
      errorContainer: Color(0xFFFEE5E7),
      onErrorContainer: AppColors.signalRedDeep,
    );
    return _build(scheme, false);
  }

  static ThemeData _build(ColorScheme scheme, bool isDark) {
    final textTheme = AppTypography.build(scheme.onSurface);

    final buttonShape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(AppRadius.sm),
    );
    final fieldShape = OutlineInputBorder(
      borderRadius: BorderRadius.circular(AppRadius.sm),
      borderSide: BorderSide(color: scheme.outline, width: 1),
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: scheme.surface,
      canvasColor: scheme.surface,
      textTheme: textTheme,
      splashFactory: InkSparkle.splashFactory,
      pageTransitionsTheme: const PageTransitionsTheme(
        builders: {
          TargetPlatform.android: PredictiveBackPageTransitionsBuilder(),
          TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
        },
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surface,
        surfaceTintColor: Colors.transparent,
        scrolledUnderElevation: 0,
        elevation: 0,
        centerTitle: false,
        foregroundColor: scheme.onSurface,
        titleTextStyle: textTheme.titleMedium?.copyWith(
          fontWeight: FontWeight.w700,
          letterSpacing: 0.4,
        ),
        iconTheme: IconThemeData(color: scheme.onSurface, size: 22),
        actionsIconTheme: IconThemeData(color: scheme.onSurface, size: 22),
      ),
      cardTheme: CardThemeData(
        color: scheme.surfaceContainer,
        elevation: 0,
        shadowColor: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          side: BorderSide(color: scheme.outline, width: 1),
        ),
        margin: EdgeInsets.zero,
      ),
      dividerTheme: DividerThemeData(
        color: scheme.outline,
        thickness: 1,
        space: 1,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: scheme.primary,
          foregroundColor: scheme.onPrimary,
          elevation: 0,
          shadowColor: Colors.transparent,
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.xl,
            vertical: AppSpacing.lg,
          ),
          shape: buttonShape,
          textStyle: const TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.4,
          ),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: scheme.primary,
          foregroundColor: scheme.onPrimary,
          elevation: 0,
          shadowColor: Colors.transparent,
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.xl,
            vertical: AppSpacing.lg,
          ),
          shape: buttonShape,
          textStyle: const TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.4,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: scheme.onSurface,
          side: BorderSide(color: scheme.outline, width: 1),
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.xl,
            vertical: AppSpacing.lg,
          ),
          shape: buttonShape,
          textStyle: const TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.4,
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: scheme.onSurface,
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.md,
          ),
          shape: buttonShape,
          textStyle: const TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.4,
          ),
        ),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(
          foregroundColor: scheme.onSurface,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.sm),
          ),
        ),
      ),
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: scheme.onSurface,
        foregroundColor: scheme.surface,
        elevation: 0,
        focusElevation: 0,
        hoverElevation: 0,
        highlightElevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
        ),
        extendedTextStyle: const TextStyle(
          fontSize: 13,
          fontWeight: FontWeight.w700,
          letterSpacing: 1.4,
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: scheme.surfaceContainer,
        border: fieldShape,
        enabledBorder: fieldShape,
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          borderSide: BorderSide(color: scheme.onSurface, width: 1.5),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          borderSide: BorderSide(color: scheme.error, width: 1),
        ),
        focusedErrorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          borderSide: BorderSide(color: scheme.error, width: 1.5),
        ),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.lg,
          vertical: AppSpacing.lg,
        ),
        labelStyle: textTheme.labelSmall?.copyWith(
          color: scheme.onSurfaceVariant,
        ),
        floatingLabelStyle: textTheme.labelSmall?.copyWith(
          color: scheme.onSurface,
        ),
        hintStyle: textTheme.bodyMedium?.copyWith(
          color: scheme.onSurfaceVariant.withValues(alpha: 0.7),
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: isDark ? AppColors.bone : AppColors.ink,
        contentTextStyle: TextStyle(
          color: isDark ? AppColors.inkBlack : AppColors.bone,
          fontWeight: FontWeight.w600,
          fontSize: 13,
          letterSpacing: 0.2,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
        ),
        actionTextColor: AppColors.signalRed,
        elevation: 0,
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: scheme.surfaceContainerLow,
        modalBackgroundColor: scheme.surfaceContainerLow,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.lg)),
        ),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: scheme.surfaceContainerLow,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          side: BorderSide(color: scheme.outline, width: 1),
        ),
        titleTextStyle: textTheme.titleLarge,
        contentTextStyle: textTheme.bodyMedium?.copyWith(
          color: scheme.onSurfaceVariant,
        ),
      ),
      listTileTheme: ListTileThemeData(
        iconColor: scheme.onSurfaceVariant,
        textColor: scheme.onSurface,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.lg,
          vertical: AppSpacing.sm,
        ),
        minVerticalPadding: AppSpacing.sm,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
        ),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: scheme.surfaceContainer,
        selectedColor: scheme.onSurface,
        checkmarkColor: scheme.surface,
        side: BorderSide(color: scheme.outline, width: 1),
        labelStyle: textTheme.labelSmall?.copyWith(
          color: scheme.onSurface,
        ),
        secondaryLabelStyle: textTheme.labelSmall?.copyWith(
          color: scheme.surface,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
        ),
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: scheme.surface,
        elevation: 0,
        surfaceTintColor: Colors.transparent,
        indicatorColor: Colors.transparent,
        overlayColor: WidgetStatePropertyAll(
          scheme.onSurface.withValues(alpha: 0.04),
        ),
        height: 64,
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return textTheme.labelSmall?.copyWith(
            fontSize: 9.5,
            color: selected ? scheme.onSurface : scheme.onSurfaceVariant,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.4,
          );
        }),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return IconThemeData(
            size: 22,
            color: selected ? scheme.onSurface : scheme.onSurfaceVariant,
          );
        }),
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(
        color: AppColors.signalRed,
        linearTrackColor: scheme.surfaceContainerHigh,
        circularTrackColor: scheme.surfaceContainerHigh,
        refreshBackgroundColor: scheme.surfaceContainer,
      ),
      sliderTheme: SliderThemeData(
        trackHeight: 2,
        activeTrackColor: scheme.onSurface,
        inactiveTrackColor: scheme.surfaceContainerHigh,
        thumbColor: scheme.onSurface,
        overlayColor: scheme.onSurface.withValues(alpha: 0.08),
        valueIndicatorColor: scheme.onSurface,
        valueIndicatorTextStyle: TextStyle(color: scheme.surface),
      ),
      switchTheme: SwitchThemeData(
        trackOutlineColor: WidgetStatePropertyAll(scheme.outline),
        trackColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) return scheme.onSurface;
          return scheme.surfaceContainerHigh;
        }),
        thumbColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) return scheme.surface;
          return scheme.onSurfaceVariant;
        }),
      ),
    );
  }
}
