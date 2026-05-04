/// Server-side analysis result, mapped from the new world-trajectory schema.
///
/// Source of truth for the JSON shape lives in
/// `server/app/pipeline/process_job.py`.
library;

import 'dart:ui';

import '../analysis/ball_track_models.dart';

class AnalysisResult {
  const AnalysisResult({
    required this.track,
    required this.worldTrajectory,
    required this.events,
    required this.lbw,
    required this.calibrationQuality,
    required this.warnings,
  });

  final BallTrackResult track;
  final WorldTrajectory worldTrajectory;
  final AnalysisEvents? events;
  final LbwResult? lbw;
  final CalibrationQuality calibrationQuality;
  final List<String> warnings;

  static AnalysisResult fromServerJson(Map<String, Object?> json) {
    final imageSize = _requireMap(json, 'image_size');
    final width = _requireInt(imageSize, 'width');
    final height = _requireInt(imageSize, 'height');

    final track = BallTrackResult.empty(width: width, height: height);
    final trackJson = json['track'];
    final pixelTrack = trackJson is Map
        ? _parsePixelTrack(trackJson.cast<String, Object?>(), width: width, height: height)
        : track;

    final worldJson = json['world_trajectory'];
    final world = worldJson is Map
        ? WorldTrajectory.fromJson(worldJson.cast<String, Object?>())
        : WorldTrajectory.empty();

    AnalysisEvents? events;
    final eventsJson = json['events'];
    if (eventsJson is Map) {
      events = AnalysisEvents.fromJson(eventsJson.cast<String, Object?>());
    }

    LbwResult? lbw;
    final lbwJson = json['lbw'];
    if (lbwJson is Map) {
      lbw = LbwResult.fromJson(lbwJson.cast<String, Object?>());
    }

    final calJson = json['calibration'];
    CalibrationQuality calQuality = CalibrationQuality.unknown();
    if (calJson is Map) {
      final qual = (calJson.cast<String, Object?>())['quality'];
      if (qual is Map) {
        calQuality = CalibrationQuality.fromJson(qual.cast<String, Object?>());
      }
    }

    final warnings = <String>[];
    final diag = json['diagnostics'];
    if (diag is Map) {
      final w = diag['warnings'];
      if (w is List) {
        for (final v in w) {
          if (v is String && v.isNotEmpty) warnings.add(v);
        }
      }
    }

    return AnalysisResult(
      track: pixelTrack,
      worldTrajectory: world,
      events: events,
      lbw: lbw,
      calibrationQuality: calQuality,
      warnings: List.unmodifiable(warnings),
    );
  }
}

/// 3D ball trajectory in world coordinates (metres).  The pitch frame is
/// X along the pitch length (0 = striker crease), Y across (positive off
/// side for right-hander), Z up.  `points` are observed-and-smoothed
/// positions from the bundle-adjusted projectile fit; `predictedToStumps`
/// extrapolates from the impact point to the stump plane.
class WorldTrajectory {
  const WorldTrajectory({
    required this.points,
    required this.predictedToStumps,
    this.fit,
  });

  factory WorldTrajectory.empty() => const WorldTrajectory(
        points: <WorldPointM>[],
        predictedToStumps: <WorldPointM>[],
        fit: null,
      );

  final List<WorldPointM> points;
  final List<WorldPointM> predictedToStumps;
  final ProjectileFitInfo? fit;

  bool get hasTrajectory => points.length >= 2;

  static WorldTrajectory fromJson(Map<String, Object?> json) {
    final pts = <WorldPointM>[];
    final ptsJson = json['points_m'];
    if (ptsJson is List) {
      for (final v in ptsJson) {
        if (v is! Map) continue;
        final m = v.cast<String, Object?>();
        final p = WorldPointM.fromJson(m);
        if (p != null) pts.add(p);
      }
    }
    final pred = <WorldPointM>[];
    final predJson = json['predicted_to_stumps_m'];
    if (predJson is List) {
      for (final v in predJson) {
        if (v is! Map) continue;
        final m = v.cast<String, Object?>();
        final p = WorldPointM.fromJson(m);
        if (p != null) pred.add(p);
      }
    }

    ProjectileFitInfo? fit;
    final fitJson = json['fit'];
    if (fitJson is Map) {
      fit = ProjectileFitInfo.fromJson(fitJson.cast<String, Object?>());
    }
    return WorldTrajectory(
      points: List.unmodifiable(pts),
      predictedToStumps: List.unmodifiable(pred),
      fit: fit,
    );
  }
}

class WorldPointM {
  const WorldPointM({
    required this.tMs,
    required this.x,
    required this.y,
    required this.z,
    this.confidence,
  });

  final int tMs;
  final double x;
  final double y;
  final double z;
  final double? confidence;

  static WorldPointM? fromJson(Map<String, Object?> m) {
    final t = _readInt(m, 't_ms');
    final x = _readDouble(m, 'x');
    final y = _readDouble(m, 'y');
    final z = _readDouble(m, 'z');
    if (t == null || x == null || y == null || z == null) return null;
    return WorldPointM(
      tMs: t, x: x, y: y, z: z,
      confidence: _readDouble(m, 'confidence'),
    );
  }

  Map<String, double> toViewerJson() => {'x': x, 'y': y, 'z': z};
}

class ProjectileFitInfo {
  const ProjectileFitInfo({
    required this.x0, required this.y0, required this.z0,
    required this.vx, required this.vy, required this.vz,
    required this.bounceTMs,
    required this.rmsM,
  });

  final double x0, y0, z0;
  final double vx, vy, vz;
  final double? bounceTMs;
  final double rmsM;

  static ProjectileFitInfo fromJson(Map<String, Object?> m) {
    return ProjectileFitInfo(
      x0: _readDouble(m, 'x0') ?? 0,
      y0: _readDouble(m, 'y0') ?? 0,
      z0: _readDouble(m, 'z0') ?? 0,
      vx: _readDouble(m, 'vx') ?? 0,
      vy: _readDouble(m, 'vy') ?? 0,
      vz: _readDouble(m, 'vz') ?? 0,
      bounceTMs: _readDouble(m, 'bounce_t_ms'),
      rmsM: _readDouble(m, 'rms_m') ?? 0,
    );
  }
}

/// Pixel-space ball detections.  Used by the 2D overlay on the captured frame
/// (debug/inspection only — no longer feeds the 3D viewer).
BallTrackResult _parsePixelTrack(
  Map<String, Object?> json, {
  required int width,
  required int height,
}) {
  final pts = <BallTrackPoint>[];
  final list = json['image_points'];
  if (list is List) {
    for (final v in list) {
      if (v is! Map) continue;
      final m = v.cast<String, Object?>();
      final t = _readInt(m, 't_ms');
      final u = _readDouble(m, 'u');
      final vx = _readDouble(m, 'v');
      final c = _readDouble(m, 'confidence') ?? 0.5;
      if (t == null || u == null || vx == null) continue;
      pts.add(BallTrackPoint(t: t, p: Offset(u, vx), confidence: c));
    }
  }
  return BallTrackResult(points: pts, width: width, height: height);
}

/// World-space event indices into `WorldTrajectory.points`.
class AnalysisEvents {
  const AnalysisEvents({required this.bounce, required this.impact});

  final EventPointM? bounce;
  final EventPointM? impact;

  static AnalysisEvents fromJson(Map<String, Object?> json) {
    return AnalysisEvents(
      bounce: EventPointM.fromJson(json['bounce']),
      impact: EventPointM.fromJson(json['impact']),
    );
  }
}

class EventPointM {
  const EventPointM({required this.tMs, required this.xM, required this.yM, this.zM});

  final int tMs;
  final double xM;
  final double yM;
  final double? zM;

  static EventPointM? fromJson(Object? json) {
    if (json is! Map) return null;
    final m = json.cast<String, Object?>();
    final t = _readInt(m, 't_ms');
    final x = _readDouble(m, 'x_m');
    final y = _readDouble(m, 'y_m');
    if (t == null || x == null || y == null) return null;
    return EventPointM(tMs: t, xM: x, yM: y, zM: _readDouble(m, 'z_m'));
  }
}

class CalibrationQuality {
  const CalibrationQuality({required this.score, required this.reprojErrorPx, required this.notes});

  factory CalibrationQuality.unknown() =>
      const CalibrationQuality(score: null, reprojErrorPx: null, notes: <String>[]);

  final double? score;
  final double? reprojErrorPx;
  final List<String> notes;

  static CalibrationQuality fromJson(Map<String, Object?> json) {
    final notes = <String>[];
    final n = json['notes'];
    if (n is List) {
      for (final v in n) {
        if (v is String) notes.add(v);
      }
    }
    return CalibrationQuality(
      score: _readDouble(json, 'score'),
      reprojErrorPx: _readDouble(json, 'reproj_error_px'),
      notes: List.unmodifiable(notes),
    );
  }
}

enum LbwDecisionKey { out, notOut, umpiresCall }

class LbwResult {
  const LbwResult({
    required this.decision,
    required this.reason,
    required this.pitchedInLine,
    required this.impactInLine,
    required this.wicketsHitting,
    required this.yAtStumpsM,
    required this.zAtStumpsM,
    required this.stumpXM,
    required this.confidence,
  });

  final LbwDecisionKey decision;
  final String reason;
  final bool pitchedInLine;
  final bool impactInLine;
  final bool wicketsHitting;
  final double? yAtStumpsM;
  final double? zAtStumpsM;
  final double stumpXM;
  final double confidence;

  static LbwResult fromJson(Map<String, Object?> json) {
    final decisionRaw = json['decision'];
    final decision = switch (decisionRaw) {
      'out' => LbwDecisionKey.out,
      'not_out' => LbwDecisionKey.notOut,
      'umpires_call' => LbwDecisionKey.umpiresCall,
      _ => throw const FormatException('Invalid lbw.decision'),
    };

    final checks = _requireMap(json, 'checks');
    final pred = _requireMap(json, 'prediction');
    return LbwResult(
      decision: decision,
      reason: (json['reason'] as String?)?.trim() ?? '',
      pitchedInLine: (checks['pitching_in_line'] as bool?) ?? false,
      impactInLine: (checks['impact_in_line'] as bool?) ?? false,
      wicketsHitting: (checks['wickets_hitting'] as bool?) ?? false,
      yAtStumpsM: _readDouble(pred, 'y_at_stumps_m'),
      zAtStumpsM: _readDouble(pred, 'z_at_stumps_m'),
      stumpXM: _readDouble(pred, 'stump_x_m') ?? 0,
      confidence: _readDouble(pred, 'confidence') ?? 0.0,
    );
  }
}

// ---------------------------------------------------------------------------
Map<String, Object?> _requireMap(Map<String, Object?> json, String key) {
  final v = json[key];
  if (v is Map) return v.cast<String, Object?>();
  throw FormatException('Missing or invalid $key');
}

int _requireInt(Map<String, Object?> json, String key) {
  final v = json[key];
  if (v is num) return v.round();
  throw FormatException('Missing or invalid $key');
}

int? _readInt(Map<String, Object?> json, String key) {
  final v = json[key];
  return v is num ? v.round() : null;
}

double? _readDouble(Map<String, Object?> json, String key) {
  final v = json[key];
  return v is num ? v.toDouble() : null;
}
