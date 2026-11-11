import 'package:flutter/material.dart';

import '../api/analysis_result.dart';

// floodlit-navy neutrals from the 3D replay, one blue for actions; red, green and amber belong to verdicts only
class AppColors {
  AppColors._();

  // behind video, the camera preview and the share card, in both themes
  static const video = Color(0xFF070D18); // oklch(0.15 0.025 260)
  static const onVideo = Color(0xFFF2F5FA); // oklch(0.97 0.006 260)
  static const videoPanel = Color(0xCC0E1828);

  // the tracked ball path, and the predicted one after it
  static const track = Color(0xFFFF4D3D); // oklch(0.67 0.21 30)
  static const predicted = Color(0xFF8FD3FF); // oklch(0.83 0.09 235)

  static const out = Color(0xFFD23A2F); // oklch(0.57 0.19 29)
  static const notOut = Color(0xFF1F9450); // oklch(0.58 0.14 152)
  static const umpiresCall = Color(0xFFE09A1A); // oklch(0.74 0.15 75)
  static const _umpiresInk = Color(0xFF261A04);

  static Color? verdict(LbwDecisionKey? d) => switch (d) {
    LbwDecisionKey.out => out,
    LbwDecisionKey.notOut => notOut,
    LbwDecisionKey.umpiresCall => umpiresCall,
    LbwDecisionKey.cantTell || null => null,
  };

  // a check tile's colour from the server's tone for that row
  static Color? tone(Object? t) => switch (t) {
    'out' => out,
    'not_out' => notOut,
    'umpires_call' => umpiresCall,
    _ => null,
  };

  // amber is too light for pale text, the red and green are not
  static Color onVerdict(Color fill) =>
      fill == umpiresCall ? _umpiresInk : onVideo;

  static ColorScheme scheme(Brightness b) {
    final base = ColorScheme.fromSeed(
      seedColor: const Color(0xFF1A5FD0),
      brightness: b,
    );
    return b == Brightness.light
        ? base.copyWith(
            primary: const Color(0xFF1A5FD0), // oklch(0.52 0.18 260)
            onPrimary: const Color(0xFFF4F7FE),
            primaryContainer: const Color(0xFFDCE7FC),
            onPrimaryContainer: const Color(0xFF0B2A62),
            secondaryContainer: const Color(0xFFE0E6F0),
            onSecondaryContainer: const Color(0xFF1A2638),
            // a cool blue-grey page with lighter panels on it, readable in the sun
            surface: const Color(0xFFE9EEF5), // oklch(0.95 0.01 255)
            surfaceDim: const Color(0xFFD5DCE6),
            surfaceBright: const Color(0xFFF6F8FB),
            surfaceContainerLowest: const Color(0xFFFBFCFE),
            surfaceContainerLow: const Color(0xFFF5F7FB),
            surfaceContainer: const Color(0xFFEFF3F8),
            surfaceContainerHigh: const Color(0xFFDFE5EE),
            surfaceContainerHighest: const Color(0xFFD5DCE7),
            onSurface: const Color(0xFF0E1829), // oklch(0.2 0.03 260)
            onSurfaceVariant: const Color(0xFF475670),
            outline: const Color(0xFF7D8BA1),
            outlineVariant: const Color(0xFFC6CFDC),
            error: out,
            onError: onVideo,
          )
        : base.copyWith(
            primary: const Color(0xFF6CB2FF), // oklch(0.75 0.13 250)
            onPrimary: const Color(0xFF041D3D),
            primaryContainer: const Color(0xFF14365F),
            onPrimaryContainer: const Color(0xFFD3E5FF),
            secondaryContainer: const Color(0xFF1F2D45),
            onSecondaryContainer: const Color(0xFFD5DEEC),
            surface: const Color(0xFF0B1322), // oklch(0.18 0.03 260)
            surfaceDim: const Color(0xFF0B1322),
            surfaceBright: const Color(0xFF2A3854),
            surfaceContainerLowest: const Color(0xFF070D18),
            surfaceContainerLow: const Color(0xFF101A2C),
            surfaceContainer: const Color(0xFF142034),
            surfaceContainerHigh: const Color(0xFF1A283F),
            surfaceContainerHighest: const Color(0xFF22314B),
            onSurface: const Color(0xFFE5EBF4),
            onSurfaceVariant: const Color(0xFFA2B0C5),
            outline: const Color(0xFF5D6C84),
            outlineVariant: const Color(0xFF283752),
            error: const Color(0xFFFF7D6E),
            onError: const Color(0xFF2B0704),
          );
  }
}
