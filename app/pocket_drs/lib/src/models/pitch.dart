import '../analysis/calibration_config.dart';

class Pitch {
  const Pitch({
    required this.id,
    required this.name,
    required this.createdAt,
    required this.updatedAt,
    this.calibration,
  });

  final String id;
  final String name;
  final DateTime createdAt;
  final DateTime updatedAt;
  final CalibrationConfig? calibration;

  bool get isCalibrated {
    final c = calibration;
    return c != null && c.pitchCalibration != null;
  }

  Pitch copyWith({
    String? name,
    DateTime? updatedAt,
    CalibrationConfig? calibration,
    bool clearCalibration = false,
  }) {
    return Pitch(
      id: id,
      name: name ?? this.name,
      createdAt: createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
      calibration: clearCalibration ? null : (calibration ?? this.calibration),
    );
  }

  Map<String, Object?> toJson() {
    return <String, Object?>{
      'id': id,
      'name': name,
      'createdAt': createdAt.toIso8601String(),
      'updatedAt': updatedAt.toIso8601String(),
      if (calibration != null) 'calibration': calibration!.toJson(),
    };
  }

  static Pitch fromJson(Map<String, Object?> json) {
    String readString(String key) {
      final v = json[key];
      if (v is String && v.trim().isNotEmpty) return v;
      throw FormatException('Expected string $key');
    }

    DateTime readDateTime(String key) {
      final v = json[key];
      if (v is String) return DateTime.parse(v);
      throw FormatException('Expected datetime string $key');
    }

    CalibrationConfig? readCalibration() {
      final raw = json['calibration'];
      if (raw == null) return null;
      if (raw is! Map<String, Object?>) {
        throw FormatException('Expected calibration object');
      }
      return CalibrationConfig.fromJson(raw);
    }

    return Pitch(
      id: readString('id'),
      name: readString('name'),
      createdAt: readDateTime('createdAt'),
      updatedAt: readDateTime('updatedAt'),
      calibration: readCalibration(),
    );
  }
}
