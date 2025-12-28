import 'pitch_calibration.dart';

class CalibrationConfig {
  const CalibrationConfig({
    required this.pitchLengthM,
    required this.pitchWidthM,
    required this.stumpHeightM,
    required this.cameraHeightM,
    required this.cameraDistanceToStumpsM,
    required this.cameraLateralOffsetM,
    this.ballImagePath,
    this.pitchCalibration,
  });

  /// Pitch length (stump-to-stump) in meters.
  final double pitchLengthM;

  /// Pitch width in meters (roughly 10 ft ≈ 3.05m).
  final double pitchWidthM;

  /// Stump height in meters.
  final double stumpHeightM;

  /// Camera height from ground in meters.
  final double cameraHeightM;

  /// Horizontal distance from camera to striker stumps in meters.
  final double cameraDistanceToStumpsM;

  /// Lateral offset of camera from the pitch center line in meters.
  ///
  /// Positive means camera is towards off-side; negative towards leg-side.
  final double cameraLateralOffsetM;

  /// Optional pitch plane calibration (pixel taps). When set, we can map
  /// tracked pixels to pitch-plane meters.
  final PitchCalibration? pitchCalibration;

  /// Optional reference photo of the match ball captured during calibration.
  ///
  /// This is stored as a local file path on-device.
  final String? ballImagePath;

  static CalibrationConfig defaults() {
    return const CalibrationConfig(
      pitchLengthM: 20.12,
      pitchWidthM: 3.05,
      stumpHeightM: 0.711,
      cameraHeightM: 1.6,
      cameraDistanceToStumpsM: 18.0,
      cameraLateralOffsetM: 0.0,
    );
  }

  List<String> validate() {
    final errors = <String>[];

    void range(
      String name,
      double value, {
      required double min,
      required double max,
    }) {
      if (value.isNaN || value.isInfinite) {
        errors.add('$name must be a valid number');
        return;
      }
      if (value < min || value > max) {
        errors.add('$name must be between $min and $max');
      }
    }

    range('Pitch length (m)', pitchLengthM, min: 10, max: 30);
    range('Pitch width (m)', pitchWidthM, min: 1.5, max: 6);
    range('Stump height (m)', stumpHeightM, min: 0.4, max: 1.2);
    range('Camera height (m)', cameraHeightM, min: 0.2, max: 10);
    range('Camera distance (m)', cameraDistanceToStumpsM, min: 1, max: 60);
    range('Camera lateral offset (m)', cameraLateralOffsetM, min: -20, max: 20);

    if (pitchCalibration != null && pitchCalibration!.imagePoints.length != 4) {
      errors.add('Pitch calibration must have 4 points');
    }

    return errors;
  }

  Map<String, Object?> toJson() {
    return <String, Object?>{
      'pitchLengthM': pitchLengthM,
      'pitchWidthM': pitchWidthM,
      'stumpHeightM': stumpHeightM,
      'cameraHeightM': cameraHeightM,
      'cameraDistanceToStumpsM': cameraDistanceToStumpsM,
      'cameraLateralOffsetM': cameraLateralOffsetM,
      if (ballImagePath != null) 'ballImagePath': ballImagePath,
      if (pitchCalibration != null) 'pitchCalibration': pitchCalibration!.toJson(),
    };
  }

  static CalibrationConfig fromJson(Map<String, Object?> json) {
        String? readStringOrNull(String key) {
          final v = json[key];
          if (v == null) return null;
          if (v is String) {
            final s = v.trim();
            return s.isEmpty ? null : s;
          }
          throw FormatException('Expected string $key');
        }
    double readNum(String key) {
      final v = json[key];
      if (v is num) return v.toDouble();
      throw FormatException('Expected numeric $key');
    }

    PitchCalibration? readPitchCalibration() {
      final raw = json['pitchCalibration'];
      if (raw == null) return null;
      if (raw is! Map<String, Object?>) {
        throw FormatException('Expected pitchCalibration object');
      }
      return PitchCalibration.fromJson(raw);
    }

    return CalibrationConfig(
      pitchLengthM: readNum('pitchLengthM'),
      pitchWidthM: readNum('pitchWidthM'),
      stumpHeightM: readNum('stumpHeightM'),
      cameraHeightM: readNum('cameraHeightM'),
      cameraDistanceToStumpsM: readNum('cameraDistanceToStumpsM'),
      cameraLateralOffsetM: readNum('cameraLateralOffsetM'),
      ballImagePath: readStringOrNull('ballImagePath'),
      pitchCalibration: readPitchCalibration(),
    );
  }

  CalibrationConfig copyWith({
    double? pitchLengthM,
    double? pitchWidthM,
    double? stumpHeightM,
    double? cameraHeightM,
    double? cameraDistanceToStumpsM,
    double? cameraLateralOffsetM,
    String? ballImagePath,
    PitchCalibration? pitchCalibration,
    bool clearPitchCalibration = false,
  }) {
    return CalibrationConfig(
      pitchLengthM: pitchLengthM ?? this.pitchLengthM,
      pitchWidthM: pitchWidthM ?? this.pitchWidthM,
      stumpHeightM: stumpHeightM ?? this.stumpHeightM,
      cameraHeightM: cameraHeightM ?? this.cameraHeightM,
      cameraDistanceToStumpsM: cameraDistanceToStumpsM ?? this.cameraDistanceToStumpsM,
      cameraLateralOffsetM: cameraLateralOffsetM ?? this.cameraLateralOffsetM,
      ballImagePath: ballImagePath ?? this.ballImagePath,
      pitchCalibration: clearPitchCalibration ? null : (pitchCalibration ?? this.pitchCalibration),
    );
  }
}
