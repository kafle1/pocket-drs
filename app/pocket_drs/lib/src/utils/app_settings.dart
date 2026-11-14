import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

enum SpeedUnit {
  kmh('km/h'),
  mph('mph');

  const SpeedUnit(this.label);
  final String label;
}

/// The stumps in use; the server scales the frame from their height and width.
enum StumpSize {
  regulation('Regulation', '28 × 9 in', 0.711, 0.2286),
  junior('Junior', '27 × 8 in', 0.6858, 0.2032),
  small('Small', '24 × 7 in', 0.6096, 0.1778);

  const StumpSize(this.label, this.inches, this.heightM, this.widthM);
  final String label;
  final String inches;
  final double heightM;
  final double widthM;
}

/// The ball in use; the server looks for different colours and bounce on each.
enum BallType {
  tennis('Tennis'),
  leather('Leather'),
  tape('Taped tennis');

  const BallType(this.label);
  final String label;
}

/// The pitch, stumps and ball in use, which set the scale and what the server looks for.
typedef PitchSetup = ({double lengthM, StumpSize stumps, BallType ball});

/// Pitch length in metres with how a club cricketer says it.
String pitchLabel(double metres) {
  final yards = metres / AppSettings.yardM;
  final whole = (yards - yards.round()).abs() < 0.05;
  return whole ? '${yards.round()} yd' : '${metres.toStringAsFixed(1)} m';
}

class AppSettings {
  static const _kThemeMode = 'themeMode_v1';
  static const _kSpeedUnit = 'speedUnit_v1';
  static const _kAutoDeleteSource = 'autoDeleteSource_v1';
  static const _kPitchLength = 'pitchLength_v1';
  static const _kStumpSize = 'stumpSize_v1';
  static const _kGuideSeen = 'filmingGuideSeen_v1';
  static const _kBallType = 'ballType_v1';
  static const _kHand = 'batterHand_v1';

  static const yardM = 0.9144;
  static const fullPitchM = 22 * yardM;
  static const pitchPresetYards = [22, 18, 16];
  static const minPitchM = 10.0;
  static const maxPitchM = 25.0;

  static Future<ThemeMode> getThemeMode() async {
    try {
      final p = await SharedPreferences.getInstance();
      return switch (p.getString(_kThemeMode)) {
        'light' => ThemeMode.light,
        'dark' => ThemeMode.dark,
        _ => ThemeMode.system,
      };
    } catch (_) {
      return ThemeMode.system;
    }
  }

  static Future<SpeedUnit> getSpeedUnit() async {
    try {
      final p = await SharedPreferences.getInstance();
      final raw = (p.getString(_kSpeedUnit) ?? 'kmh').trim();
      return raw == 'mph' ? SpeedUnit.mph : SpeedUnit.kmh;
    } catch (_) {
      return SpeedUnit.kmh;
    }
  }

  static Future<void> setSpeedUnit(SpeedUnit unit) async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_kSpeedUnit, unit == SpeedUnit.mph ? 'mph' : 'kmh');
  }

  static Future<bool> getAutoDeleteSource() async {
    try {
      final p = await SharedPreferences.getInstance();
      return p.getBool(_kAutoDeleteSource) ?? false;
    } catch (_) {
      return false;
    }
  }

  static Future<void> setAutoDeleteSource(bool value) async {
    final p = await SharedPreferences.getInstance();
    await p.setBool(_kAutoDeleteSource, value);
  }

  static Future<double> getPitchLength() async {
    try {
      final p = await SharedPreferences.getInstance();
      final v = p.getDouble(_kPitchLength) ?? fullPitchM;
      return v >= minPitchM && v <= maxPitchM ? v : fullPitchM;
    } catch (_) {
      return fullPitchM;
    }
  }

  static Future<void> setPitchLength(double metres) async {
    final p = await SharedPreferences.getInstance();
    await p.setDouble(_kPitchLength, metres);
  }

  static Future<PitchSetup> getPitchSetup() async => (
    lengthM: await getPitchLength(),
    stumps: await getStumpSize(),
    ball: await getBallType(),
  );

  // the length is only saved once the player picks it, so its absence means never asked
  static Future<bool> getPitchChosen() async {
    try {
      final p = await SharedPreferences.getInstance();
      return p.containsKey(_kPitchLength);
    } catch (_) {
      return false;
    }
  }

  static Future<BallType> getBallType() async {
    try {
      final p = await SharedPreferences.getInstance();
      final raw = p.getString(_kBallType);
      return BallType.values.firstWhere(
        (b) => b.name == raw,
        orElse: () => BallType.tennis,
      );
    } catch (_) {
      return BallType.tennis;
    }
  }

  static Future<void> setBallType(BallType ball) async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_kBallType, ball.name);
  }

  /// The batter's hand from the last ball sent, 'right' or 'left'.
  static Future<String> getHand() async {
    try {
      final p = await SharedPreferences.getInstance();
      return p.getString(_kHand) == 'left' ? 'left' : 'right';
    } catch (_) {
      return 'right';
    }
  }

  static Future<void> setHand(String hand) async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_kHand, hand);
  }

  static Future<StumpSize> getStumpSize() async {
    try {
      final p = await SharedPreferences.getInstance();
      final raw = p.getString(_kStumpSize);
      return StumpSize.values.firstWhere(
        (s) => s.name == raw,
        orElse: () => StumpSize.regulation,
      );
    } catch (_) {
      return StumpSize.regulation;
    }
  }

  static Future<void> setStumpSize(StumpSize size) async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_kStumpSize, size.name);
  }

  static Future<bool> getGuideSeen() async {
    try {
      final p = await SharedPreferences.getInstance();
      return p.getBool(_kGuideSeen) ?? false;
    } catch (_) {
      return false;
    }
  }

  static Future<void> setGuideSeen() async {
    final p = await SharedPreferences.getInstance();
    await p.setBool(_kGuideSeen, true);
  }

  static Future<void> setThemeMode(ThemeMode mode) async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_kThemeMode, mode.name);
  }
}
