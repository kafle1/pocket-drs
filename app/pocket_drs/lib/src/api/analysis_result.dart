import 'dart:ui';

import '../analysis/ball_track_models.dart';

class AnalysisResult {
  const AnalysisResult({
    required this.track,
    required this.pitchPlane,
    required this.events,
    required this.lbw,
    required this.warnings,
  });

  final BallTrackResult track;
  final List<PitchPlanePointM> pitchPlane;
  final AnalysisEvents? events;
  final LbwResult? lbw;
  final List<String> warnings;

  static AnalysisResult fromServerJson(Map<String, Object?> json) {
    final imageSize = _requireMap(json, 'image_size');
    final width = _requireInt(imageSize, 'width');
    final height = _requireInt(imageSize, 'height');

    final trackJson = _requireMap(json, 'track');
    final pointsJson = _requireList(trackJson, 'points');

    final points = <BallTrackPoint>[];
    for (final v in pointsJson) {
      if (v is! Map) continue;
      final m = v.cast<String, Object?>();
      final t = _readInt(m, 't_ms');
      final x = _readDouble(m, 'x_px');
      final y = _readDouble(m, 'y_px');
      final c = _readDouble(m, 'confidence');
      if (t == null || x == null || y == null || c == null) continue;
      points.add(BallTrackPoint(t: t, p: Offset(x, y), confidence: c));
    }
    if (points.isEmpty) {
      throw const FormatException('Server result contains no track points');
    }

    final pitchPlanePoints = <PitchPlanePointM>[];
    final pitchPlaneJson = json['pitch_plane'];
    if (pitchPlaneJson is Map) {
      final pts = _requireList(pitchPlaneJson.cast<String, Object?>(), 'points_m');
      for (final v in pts) {
        if (v is! Map) continue;
        final m = v.cast<String, Object?>();
        final t = _readInt(m, 't_ms');
        final x = _readDouble(m, 'x_m');
        final y = _readDouble(m, 'y_m');
        if (t == null || x == null || y == null) continue;
        pitchPlanePoints.add(PitchPlanePointM(tMs: t, worldM: Offset(x, y)));
      }
    }

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

    final warnings = <String>[];
    final diagnostics = json['diagnostics'];
    if (diagnostics is Map) {
      final w = diagnostics['warnings'];
      if (w is List) {
        for (final v in w) {
          if (v is String && v.isNotEmpty) warnings.add(v);
        }
      }
    }

    return AnalysisResult(
      track: BallTrackResult(points: points, width: width, height: height),
      pitchPlane: List.unmodifiable(pitchPlanePoints),
      events: events,
      lbw: lbw,
      warnings: List.unmodifiable(warnings),
    );
  }
}

class PitchPlanePointM {
  const PitchPlanePointM({required this.tMs, required this.worldM});

  final int tMs;
  final Offset worldM;
}

class AnalysisEvents {
  const AnalysisEvents({required this.bounceIndex, required this.impactIndex});

  final int bounceIndex;
  final int impactIndex;

  static AnalysisEvents fromJson(Map<String, Object?> json) {
    final bounce = _requireMap(json, 'bounce');
    final impact = _requireMap(json, 'impact');
    return AnalysisEvents(
      bounceIndex: _requireInt(bounce, 'index'),
      impactIndex: _requireInt(impact, 'index'),
    );
  }
}

enum LbwDecisionKey {
  out,
  notOut,
  umpiresCall,
}

class LbwResult {
  const LbwResult({
    required this.decision,
    required this.likelyOut,
    required this.pitchedInLine,
    required this.impactInLine,
    required this.wicketsHitting,
    required this.yAtStumpsM,
    required this.reason,
  });

  final LbwDecisionKey decision;
  final bool likelyOut;
  final bool pitchedInLine;
  final bool impactInLine;
  final bool wicketsHitting;
  final double yAtStumpsM;
  final String reason;

  static LbwResult fromJson(Map<String, Object?> json) {
    final decisionRaw = json['decision'];
    final decision = switch (decisionRaw) {
      'out' => LbwDecisionKey.out,
      'not_out' => LbwDecisionKey.notOut,
      'umpires_call' => LbwDecisionKey.umpiresCall,
      _ => throw const FormatException('Invalid lbw.decision')
    };

    final likelyOut = _requireBool(json, 'likely_out');

    final checks = _requireMap(json, 'checks');
    final pitched = _requireBool(checks, 'pitching_in_line');
    final impact = _requireBool(checks, 'impact_in_line');
    final wickets = _requireBool(checks, 'wickets_hitting');

    final prediction = _requireMap(json, 'prediction');
    final yAtStumps = _requireDouble(prediction, 'y_at_stumps_m');

    final reason = json['reason'];
    if (reason is! String || reason.trim().isEmpty) {
      throw const FormatException('Missing lbw.reason');
    }

    return LbwResult(
      decision: decision,
      likelyOut: likelyOut,
      pitchedInLine: pitched,
      impactInLine: impact,
      wicketsHitting: wickets,
      yAtStumpsM: yAtStumps,
      reason: reason,
    );
  }
}

Map<String, Object?> _requireMap(Map<String, Object?> json, String key) {
  final v = json[key];
  if (v is Map) return v.cast<String, Object?>();
  throw FormatException('Missing or invalid $key');
}

List<Object?> _requireList(Map<String, Object?> json, String key) {
  final v = json[key];
  if (v is List) return v.cast<Object?>();
  throw FormatException('Missing or invalid $key');
}

int _requireInt(Map<String, Object?> json, String key) {
  final v = json[key];
  if (v is num) return v.round();
  throw FormatException('Missing or invalid $key');
}

double _requireDouble(Map<String, Object?> json, String key) {
  final v = json[key];
  if (v is num) return v.toDouble();
  throw FormatException('Missing or invalid $key');
}

bool _requireBool(Map<String, Object?> json, String key) {
  final v = json[key];
  if (v is bool) return v;
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
