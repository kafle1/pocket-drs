import 'package:flutter/material.dart';

class AppTheme {
  // Ultra-minimal, modern palette - High contrast structural colors
  static const _primaryColor = Color(0xFF111111); // Pure dark
  static const _primaryColorDark = Color(0xFFEEEEEE); // Pure light for dark mode
  static const _accentColor = Color(0xFF3B82F6); // Clean tech blue accent
  
  // Dark theme colors
  static const _darkBg = Color(0xFF000000); // True black
  static const _darkSurface = Color(0xFF0A0A0A); // Slightly raised
  static const _darkCard = Color(0xFF121212); // Card surface
  
  // Light theme colors  
  static const _lightBg = Color(0xFFFDFDFD); // Off-white
  static const _lightSurface = Color(0xFFFFFFFF);
  static const _lightCard = Color(0xFFF7F7F7);

  static const _errorLight = Color(0xFFE63946);
  static const _errorDark = Color(0xFFFF5A5F);
  static const _successColor = Color(0xFF2A9D8F);

  static ThemeData light() {
    final colorScheme = ColorScheme.light(
      primary: _primaryColor,
      secondary: _accentColor,
      error: _errorLight,
      surface: _lightSurface,
      surfaceContainer: _lightCard,
      surfaceContainerLowest: _lightBg,
      surfaceContainerHighest: const Color(0xFFEAEAEA),
      primaryContainer: const Color(0xFFF0F0F0),
      onPrimaryContainer: const Color(0xFF111111),
      secondaryContainer: const Color(0xFFEBF2FE),
      onSecondaryContainer: const Color(0xFF1D4ED8),
      tertiary: _successColor,
      tertiaryContainer: const Color(0xFFE0F2F1),
      onTertiaryContainer: const Color(0xFF1B6A60),
    );
    return _buildTheme(colorScheme);
  }

  static ThemeData dark() {
    final colorScheme = ColorScheme.dark(
      primary: _primaryColorDark,
      secondary: _accentColor,
      error: _errorDark,
      surface: _darkSurface,
      surfaceContainer: _darkCard,
      surfaceContainerLowest: _darkBg,
      surfaceContainerHighest: const Color(0xFF222222),
      primaryContainer: const Color(0xFF1A1A1A),
      onPrimaryContainer: const Color(0xFFEEEEEE),
      secondaryContainer: const Color(0xFF1E3A8A),
      onSecondaryContainer: const Color(0xFFDBEAFE),
      tertiary: _successColor,
      tertiaryContainer: const Color(0xFF1B6A60),
      onTertiaryContainer: const Color(0xFFE0F2F1),
    );
    return _buildTheme(colorScheme);
  }

  static ThemeData _buildTheme(ColorScheme colorScheme) {
    final isDark = colorScheme.brightness == Brightness.dark;
    
    // SF Pro / Inter typography feel
    final textTheme = TextTheme(
      displayLarge: const TextStyle(fontWeight: FontWeight.w800, letterSpacing: -1.5, fontSize: 56),
      displayMedium: const TextStyle(fontWeight: FontWeight.w800, letterSpacing: -1.0, fontSize: 48),
      displaySmall: const TextStyle(fontWeight: FontWeight.w700, letterSpacing: -0.5, fontSize: 36),
      headlineLarge: const TextStyle(fontWeight: FontWeight.w700, letterSpacing: -0.5, fontSize: 32),
      headlineMedium: const TextStyle(fontWeight: FontWeight.w700, letterSpacing: -0.5, fontSize: 28),
      headlineSmall: const TextStyle(fontWeight: FontWeight.w600, letterSpacing: -0.25, fontSize: 24),
      titleLarge: const TextStyle(fontWeight: FontWeight.w600, letterSpacing: -0.25, fontSize: 20),
      titleMedium: const TextStyle(fontWeight: FontWeight.w600, letterSpacing: 0.1, fontSize: 16),
      titleSmall: const TextStyle(fontWeight: FontWeight.w500, letterSpacing: 0.1, fontSize: 14),
      bodyLarge: const TextStyle(fontWeight: FontWeight.w400, letterSpacing: 0.15, fontSize: 16, height: 1.5),
      bodyMedium: const TextStyle(fontWeight: FontWeight.w400, letterSpacing: 0.25, fontSize: 14, height: 1.5),
      bodySmall: const TextStyle(fontWeight: FontWeight.w400, letterSpacing: 0.4, fontSize: 12, height: 1.5),
      labelLarge: const TextStyle(fontWeight: FontWeight.w600, letterSpacing: 0.5, fontSize: 14),
      labelMedium: const TextStyle(fontWeight: FontWeight.w500, letterSpacing: 0.5, fontSize: 12),
      labelSmall: const TextStyle(fontWeight: FontWeight.w500, letterSpacing: 0.5, fontSize: 11),
    ).apply(
      bodyColor: colorScheme.onSurface,
      displayColor: colorScheme.onSurface,
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: isDark ? colorScheme.surfaceContainerLowest : colorScheme.surfaceContainerLowest,
      textTheme: textTheme,
      appBarTheme: AppBarTheme(
        backgroundColor: Colors.transparent,
        foregroundColor: colorScheme.onSurface,
        elevation: 0,
        centerTitle: false,
        surfaceTintColor: Colors.transparent,
        titleTextStyle: textTheme.headlineMedium?.copyWith(color: colorScheme.onSurface),
      ),
      cardTheme: CardThemeData(
        color: colorScheme.surfaceContainer,
        elevation: 0,
        shadowColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(24),
          side: BorderSide(
            color: colorScheme.outlineVariant.withValues(alpha: isDark ? 0.1 : 0.4),
            width: 1,
          ),
        ),
        margin: EdgeInsets.zero,
      ),
      dividerTheme: DividerThemeData(
        color: colorScheme.outlineVariant.withValues(alpha: isDark ? 0.1 : 0.2),
        thickness: 1,
        space: 1,
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: colorScheme.primary,
          foregroundColor: colorScheme.onPrimary,
          elevation: 0,
          shadowColor: Colors.transparent,
          padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 20),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          textStyle: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w600,
            letterSpacing: 0.2,
          ),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: colorScheme.primary,
          foregroundColor: colorScheme.onPrimary,
          elevation: 0,
          shadowColor: Colors.transparent,
          padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 18),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          textStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 16, letterSpacing: 0.2),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: colorScheme.onSurface,
          side: BorderSide(color: colorScheme.outlineVariant.withValues(alpha: isDark ? 0.3 : 0.5), width: 1.5),
          padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 18),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          textStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 16, letterSpacing: 0.2),
        ),
      ),
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: colorScheme.primary,
        foregroundColor: colorScheme.onPrimary,
        elevation: 4,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: colorScheme.surfaceContainerHighest.withValues(alpha: isDark ? 0.2 : 0.3),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide.none,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide(color: colorScheme.outlineVariant.withValues(alpha: isDark ? 0.1 : 0.3)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide(color: colorScheme.primary, width: 2),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide(color: colorScheme.error, width: 1.5),
        ),
        focusedErrorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide(color: colorScheme.error, width: 2),
        ),
        contentPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
        labelStyle: TextStyle(fontSize: 16, fontWeight: FontWeight.w500, color: colorScheme.onSurfaceVariant),
        hintStyle: TextStyle(fontSize: 16, color: colorScheme.onSurfaceVariant.withValues(alpha: 0.6)),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: isDark ? const Color(0xFF222222) : const Color(0xFF111111),
        contentTextStyle: textTheme.bodyMedium?.copyWith(color: Colors.white, fontWeight: FontWeight.w500),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        actionTextColor: colorScheme.secondary,
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: colorScheme.surface,
        modalBackgroundColor: colorScheme.surface,
        surfaceTintColor: Colors.transparent,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(32)),
        ),
      ),
      listTileTheme: ListTileThemeData(
        iconColor: colorScheme.onSurfaceVariant,
        textColor: colorScheme.onSurface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: colorScheme.surfaceContainerHighest.withValues(alpha: isDark ? 0.5 : 0.5),
        selectedColor: colorScheme.primary,
        checkmarkColor: colorScheme.onPrimary,
        labelStyle: textTheme.labelMedium?.copyWith(
          fontWeight: FontWeight.w600,
          color: colorScheme.onSurface,
        ),
        secondaryLabelStyle: textTheme.labelMedium?.copyWith(
          fontWeight: FontWeight.w600,
          color: colorScheme.onPrimary,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: const BorderSide(color: Colors.transparent, width: 0),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: colorScheme.surface.withValues(alpha: 0.95),
        elevation: 0,
        height: 80,
        indicatorColor: colorScheme.secondaryContainer,
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return textTheme.labelMedium?.copyWith(
            fontWeight: selected ? FontWeight.w700 : FontWeight.w600,
            fontSize: 11,
            color: selected ? colorScheme.onSurface : colorScheme.onSurfaceVariant,
          );
        }),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return IconThemeData(
            size: 24,
            color: selected ? colorScheme.onSurface : colorScheme.onSurfaceVariant,
          );
        }),
      ),
    );
  }
}
