/// 4-unit spacing scale tuned for tight broadcast layouts.
class AppSpacing {
  AppSpacing._();
  static const double xxs = 2;
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 12;
  static const double lg = 16;
  static const double xl = 24;
  static const double xxl = 32;
  static const double xxxl = 48;
  static const double huge = 64;
}

/// Sharp-edged radius scale. Most surfaces are 0 (true broadcast look);
/// larger radii reserved for floating sheets and pills.
class AppRadius {
  AppRadius._();
  static const double none = 0;
  static const double xs = 2;
  static const double sm = 4;
  static const double md = 8;
  static const double lg = 12;
  static const double xl = 20;
  static const double pill = 999;
}

class AppDurations {
  AppDurations._();
  static const Duration fast = Duration(milliseconds: 160);
  static const Duration med = Duration(milliseconds: 240);
  static const Duration slow = Duration(milliseconds: 360);
}
