import 'package:flutter/material.dart';

class AppColors {
  AppColors._();

  static const seed = Color(0xFF1E6B3A);

  // behind video and the camera preview, in both themes
  static const video = Colors.black;
  static const onVideo = Colors.white;

  // the measured ball path drawn over the video
  static const track = Color(0xFFFF5252);

  // verdicts: light tones read on dark surfaces, deep tones on light ones and under white text
  static Color out(Brightness b) =>
      b == Brightness.dark ? const Color(0xFFF28B82) : const Color(0xFFC5221F);
  static Color notOut(Brightness b) =>
      b == Brightness.dark ? const Color(0xFF81C995) : const Color(0xFF137333);
  static Color umpiresCall(Brightness b) =>
      b == Brightness.dark ? const Color(0xFFFDD663) : const Color(0xFFB06000);
}
