import 'package:flutter/material.dart';

/// Cricket broadcast / Hawk-Eye telemetry palette.
/// Single signal accent (cricket-red), ink-black surfaces, pitch-green for
/// confirmations. Sharp, broadcast-grade.
class AppColors {
  AppColors._();

  // Dark surfaces — OLED-friendly ink stack.
  static const inkBlack = Color(0xFF0A0A0B);
  static const carbon = Color(0xFF131316);
  static const graphite = Color(0xFF1C1C20);
  static const slate = Color(0xFF24242A);
  static const hairlineDark = Color(0xFF2A2A30);

  // Light surfaces.
  static const paper = Color(0xFFFAFAF7);
  static const paperSurface = Color(0xFFFFFFFF);
  static const paperRaised = Color(0xFFF2F2EE);
  static const hairlineLight = Color(0xFFE2E2DC);

  // Foreground.
  static const bone = Color(0xFFF4F4F0);
  static const ash = Color(0xFF8B8B92);
  static const ink = Color(0xFF0A0A0B);
  static const inkMuted = Color(0xFF5C5C63);

  // Signal accents — single-source-of-truth for state colour across the app.
  static const signalRed = Color(0xFFFF2D2D);
  static const signalRedDeep = Color(0xFFE51F2E);
  static const pitchGreen = Color(0xFF00D957);
  static const pitchGreenDeep = Color(0xFF009E40);
  static const caution = Color(0xFFFFB400);
  static const cautionDeep = Color(0xFFD89500);

  // Decision colours — cricket DRS semantics.
  static Color decisionOut(bool dark) => dark ? signalRed : signalRedDeep;
  static Color decisionNotOut(bool dark) => dark ? pitchGreen : pitchGreenDeep;
  static Color decisionUmpire(bool dark) => dark ? caution : cautionDeep;
}
