import 'package:flutter/material.dart';

import '../api/analysis_result.dart';

// one palette with the website: oklch values in the comments, sRGB is what they land on
class AppColors {
  AppColors._();

  // behind video and the camera preview, in both themes
  static const video = Color(0xFF090C0A); // oklch(0.15 0.006 150)
  static const onVideo = Color(0xFFF7F9F7); // oklch(0.98 0.004 150)

  // the measured ball path drawn over the video
  static const track = Color(0xFFFF5252);

  static const out = Color(0xFFC9302D); // oklch(0.55 0.19 27)
  static const notOut = Color(0xFF1C8742); // oklch(0.55 0.14 150)
  static const umpiresCall = Color(0xFFD0901E); // oklch(0.70 0.14 75)
  static const _umpiresInk = Color(0xFF23190A); // oklch(0.22 0.03 75)

  // the verdict's fill in both themes; no call has none and stays neutral
  static Color? verdict(LbwDecisionKey? d) => switch (d) {
    LbwDecisionKey.out => out,
    LbwDecisionKey.notOut => notOut,
    LbwDecisionKey.umpiresCall => umpiresCall,
    null => null,
  };

  // amber is too light for pale text, the red and green are not
  static Color onVerdict(Color fill) =>
      fill == umpiresCall ? _umpiresInk : onVideo;

  static ColorScheme scheme(Brightness b) {
    final base = ColorScheme.fromSeed(seedColor: _lightPrimary, brightness: b);
    return b == Brightness.light
        ? base.copyWith(
            primary: _lightPrimary,
            onPrimary: onVideo,
            primaryContainer: const Color(0xFFD1F1DB), // oklch(0.93 0.045 155)
            onPrimaryContainer: const Color(0xFF00391B), // oklch(0.30 0.08 155)
            surface: const Color(0xFFF8FBF9), // oklch(0.985 0.004 150)
            surfaceDim: const Color(0xFFDADFDB),
            surfaceBright: const Color(0xFFF8FBF9),
            surfaceContainerLowest: const Color(0xFFFCFEFC),
            surfaceContainerLow: const Color(0xFFF2F5F3),
            surfaceContainer: const Color(0xFFEDF1EE),
            surfaceContainerHigh: const Color(0xFFE8ECE9),
            surfaceContainerHighest: const Color(0xFFE3E8E3),
            onSurface: const Color(0xFF171C18), // oklch(0.22 0.012 150)
            onSurfaceVariant: const Color(0xFF505851), // oklch(0.45 0.014 150)
            outline: const Color(0xFF818882),
            outlineVariant: const Color(0xFFD4D9D5),
            error: out,
            onError: onVideo,
          )
        : base.copyWith(
            primary: const Color(0xFF73CE95), // oklch(0.78 0.12 155)
            onPrimary: const Color(0xFF012A14), // oklch(0.25 0.06 155)
            primaryContainer: const Color(0xFF0E492A), // oklch(0.36 0.08 155)
            onPrimaryContainer: const Color(0xFFC0EACD), // oklch(0.90 0.06 155)
            surface: const Color(0xFF121613), // oklch(0.195 0.008 150)
            surfaceDim: const Color(0xFF121613),
            surfaceBright: const Color(0xFF323733),
            surfaceContainerLowest: const Color(0xFF0B0E0C),
            surfaceContainerLow: const Color(0xFF171B17),
            surfaceContainer: const Color(0xFF1B1F1C),
            surfaceContainerHigh: const Color(0xFF222723),
            surfaceContainerHighest: const Color(0xFF292E2A),
            onSurface: const Color(0xFFE5E9E6), // oklch(0.93 0.006 150)
            onSurfaceVariant: const Color(0xFFACB3AD), // oklch(0.76 0.012 150)
            outline: const Color(0xFF767C77),
            outlineVariant: const Color(0xFF3A3F3A),
            error: const Color(0xFFF47C70), // oklch(0.72 0.15 27)
            onError: const Color(0xFF2A0705),
          );
  }

  // oklch(0.52 0.13 155) sits just outside sRGB, this is it clipped the way browsers render it
  static const _lightPrimary = Color(0xFF007E46);
}
