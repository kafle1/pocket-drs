import 'package:flutter/material.dart';

class AppTheme {
  // Modern, minimal palette
  static const _primaryLight = Color(0xFF0F172A); // Slate 900
  static const _primaryDark = Color(0xFFF8FAFC); // Slate 50
  
  static const _accent = Color(0xFF10B981); // Emerald 500
  static const _accentVariant = Color(0xFF059669); // Emerald 600
  
  static const _surfaceLight = Color(0xFFFFFFFF);
  static const _backgroundLight = Color(0xFFF1F5F9); // Slate 100
  
  static const _surfaceDark = Color(0xFF1E293B); // Slate 800
  static const _backgroundDark = Color(0xFF0F172A); // Slate 900

  static ThemeData light() {
    final colorScheme = ColorScheme.light(
      primary: _primaryLight,
      onPrimary: Colors.white,
      secondary: _accent,
      onSecondary: Colors.white,
      tertiary: _accentVariant,
      onTertiary: Colors.white,
      surface: _surfaceLight,
      onSurface: _primaryLight,
      surfaceContainerHighest: const Color(0xFFE2E8F0), // Slate 200
      surfaceContainer: const Color(0xFFF8FAFC), // Slate 50
      error: const Color(0xFFEF4444), // Red 500
      onError: Colors.white,
      outline: const Color(0xFF94A3B8), // Slate 400
      outlineVariant: const Color(0xFFCBD5E1), // Slate 300
    );

    return _buildTheme(colorScheme);
  }

  static ThemeData dark() {
    final colorScheme = ColorScheme.dark(
      primary: _primaryDark,
      onPrimary: _primaryLight,
      secondary: _accent,
      onSecondary: Colors.white,
      tertiary: _accentVariant,
      onTertiary: Colors.white,
      surface: _surfaceDark,
      onSurface: const Color(0xFFF1F5F9), // Slate 100
      surfaceContainerHighest: const Color(0xFF334155), // Slate 700
      surfaceContainer: const Color(0xFF1E293B), // Slate 800
      error: const Color(0xFFF87171), // Red 400
      onError: _primaryLight,
      outline: const Color(0xFF64748B), // Slate 500
      outlineVariant: const Color(0xFF475569), // Slate 600
    );

    return _buildTheme(colorScheme);
  }

  static ThemeData _buildTheme(ColorScheme colorScheme) {
    final isDark = colorScheme.brightness == Brightness.dark;
    
    return ThemeData(
      useMaterial3: true,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: isDark ? _backgroundDark : _backgroundLight,
      appBarTheme: AppBarTheme(
        backgroundColor: isDark ? _backgroundDark : _backgroundLight,
        foregroundColor: colorScheme.onSurface,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: colorScheme.onSurface,
          fontSize: 24,
          fontWeight: FontWeight.w700,
          letterSpacing: -0.5,
        ),
      ),
      cardTheme: CardThemeData(
        color: colorScheme.surface,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(
            color: colorScheme.outlineVariant.withOpacity(0.5),
            width: 1,
          ),
        ),
        margin: const EdgeInsets.symmetric(vertical: 8, horizontal: 16),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: colorScheme.primary,
          foregroundColor: colorScheme.onPrimary,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
          textStyle: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w600,
            letterSpacing: 0.5,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: colorScheme.primary,
          side: BorderSide(color: colorScheme.outline),
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      ),
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: colorScheme.secondary,
        foregroundColor: colorScheme.onSecondary,
        elevation: 4,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: colorScheme.surfaceContainerHighest.withOpacity(0.3),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide.none,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: colorScheme.outlineVariant),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: colorScheme.primary, width: 2),
        ),
        contentPadding: const EdgeInsets.all(16),
      ),
      textTheme: TextTheme(
        displayLarge: TextStyle(
          fontSize: 32,
          fontWeight: FontWeight.w800,
          letterSpacing: -1.0,
          color: colorScheme.onSurface,
        ),
        titleLarge: TextStyle(
          fontSize: 20,
          fontWeight: FontWeight.w700,
          letterSpacing: -0.5,
          color: colorScheme.onSurface,
        ),
        bodyLarge: TextStyle(
          fontSize: 16,
          fontWeight: FontWeight.w400,
          color: colorScheme.onSurface.withOpacity(0.9),
        ),
        bodyMedium: TextStyle(
          fontSize: 14,
          fontWeight: FontWeight.w400,
          color: colorScheme.onSurface.withOpacity(0.7),
        ),
      ),
    );
  }
}
