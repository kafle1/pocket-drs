import 'package:flutter/material.dart';

/// Typography vocabulary for the DRS UI.
///
/// No custom font is bundled — we rely on the platform sans-serif but
/// characterise it via extreme weight contrast, tight display tracking,
/// monospace tabular figures, and broadcast-style ALL CAPS labels with
/// wide letter spacing.
class AppTypography {
  AppTypography._();

  static const _tabular = <FontFeature>[FontFeature.tabularFigures()];

  /// Build the full text theme. [onSurface] drives default body/display
  /// colour; individual screens can override per-text.
  static TextTheme build(Color onSurface) {
    return TextTheme(
      // Hero numerics / scoreboard-style labels.
      displayLarge: TextStyle(
        fontSize: 64,
        fontWeight: FontWeight.w900,
        letterSpacing: -2.5,
        height: 0.95,
        color: onSurface,
        fontFeatures: _tabular,
      ),
      displayMedium: TextStyle(
        fontSize: 48,
        fontWeight: FontWeight.w900,
        letterSpacing: -1.8,
        height: 1.0,
        color: onSurface,
        fontFeatures: _tabular,
      ),
      displaySmall: TextStyle(
        fontSize: 36,
        fontWeight: FontWeight.w800,
        letterSpacing: -1.0,
        height: 1.05,
        color: onSurface,
        fontFeatures: _tabular,
      ),
      headlineLarge: TextStyle(
        fontSize: 30,
        fontWeight: FontWeight.w800,
        letterSpacing: -0.6,
        height: 1.1,
        color: onSurface,
      ),
      headlineMedium: TextStyle(
        fontSize: 24,
        fontWeight: FontWeight.w800,
        letterSpacing: -0.4,
        height: 1.15,
        color: onSurface,
      ),
      headlineSmall: TextStyle(
        fontSize: 20,
        fontWeight: FontWeight.w700,
        letterSpacing: -0.2,
        height: 1.2,
        color: onSurface,
      ),
      titleLarge: TextStyle(
        fontSize: 18,
        fontWeight: FontWeight.w700,
        letterSpacing: -0.1,
        height: 1.25,
        color: onSurface,
      ),
      titleMedium: TextStyle(
        fontSize: 15,
        fontWeight: FontWeight.w600,
        letterSpacing: 0,
        height: 1.3,
        color: onSurface,
      ),
      titleSmall: TextStyle(
        fontSize: 13,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.1,
        height: 1.3,
        color: onSurface,
      ),
      bodyLarge: TextStyle(
        fontSize: 16,
        fontWeight: FontWeight.w400,
        letterSpacing: 0,
        height: 1.45,
        color: onSurface,
      ),
      bodyMedium: TextStyle(
        fontSize: 14,
        fontWeight: FontWeight.w400,
        letterSpacing: 0.05,
        height: 1.45,
        color: onSurface,
      ),
      bodySmall: TextStyle(
        fontSize: 12,
        fontWeight: FontWeight.w400,
        letterSpacing: 0.1,
        height: 1.4,
        color: onSurface,
      ),
      // Broadcast HUD all-caps labels.
      labelLarge: TextStyle(
        fontSize: 12,
        fontWeight: FontWeight.w700,
        letterSpacing: 1.8,
        height: 1.0,
        color: onSurface,
      ),
      labelMedium: TextStyle(
        fontSize: 11,
        fontWeight: FontWeight.w700,
        letterSpacing: 1.4,
        height: 1.0,
        color: onSurface,
      ),
      labelSmall: TextStyle(
        fontSize: 10,
        fontWeight: FontWeight.w700,
        letterSpacing: 1.2,
        height: 1.0,
        color: onSurface,
      ),
    );
  }

  /// Returns a copy of [style] with tabular-figure font features applied,
  /// for stat / timecode / metric displays where digits must align.
  static TextStyle? mono(TextStyle? style) =>
      style?.copyWith(fontFeatures: _tabular);
}
