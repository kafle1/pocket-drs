/// The server's review result. Its shape is documented at the top of
/// `server/app/pipeline/process_job.py`.
library;

import 'dart:ui';

class AnalysisResult {
  const AnalysisResult({
    required this.track,
    required this.worldTrajectory,
    required this.events,
    required this.lbw,
    required this.noCall,
    required this.worstMark,
    required this.overlay,
    required this.metrics,
    required this.imageWidth,
    required this.imageHeight,
    required this.warnings,
    required this.json,
  });

  /// The ball where it was seen, in the marked frame's pixels.
  final List<OverlayPoint> track;
  final WorldTrajectory worldTrajectory;
  final AnalysisEvents? events;
  final LbwResult? lbw;
  final NoCall? noCall;
  // the stump mark furthest from where the solved camera puts it, 0..7
  final int? worstMark;

  /// Pixel-space ball path projected by the server for the video overlay.
  final TrajectoryOverlay? overlay;
  final DeliveryMetrics? metrics;

  /// Pixel size of the analysed frame, the space of [overlay] and [track].
  final int imageWidth;
  final int imageHeight;
  final List<String> warnings;

  /// The server's result as sent, kept so a review can be saved and opened again.
  final Map<String, Object?> json;

  bool get hasCall => switch (lbw?.decision) {
    null || LbwDecisionKey.cantTell => false,
    _ => true,
  };

  static AnalysisResult fromServerJson(Map<String, Object?> json) {
    final imageSize = _map(json['image_size']);
    final width = _readInt(imageSize, 'width');
    final height = _readInt(imageSize, 'height');
    if (width == null || height == null) {
      throw const FormatException('Missing or invalid image_size');
    }
    final diag = _map(json['diagnostics']);
    final worst = _readInt(diag, 'worst_mark');
    final lbw = json['lbw'];
    final events = json['events'];
    return AnalysisResult(
      track: _points(_map(json['track'])['image_points']),
      worldTrajectory: WorldTrajectory.fromJson(_map(json['world_trajectory'])),
      events: events is Map ? AnalysisEvents.fromJson(_map(events)) : null,
      lbw: lbw is Map ? LbwResult.fromJson(_map(lbw)) : null,
      noCall: NoCall.fromJson(json['no_call']),
      worstMark: worst != null && worst >= 0 && worst < 8 ? worst : null,
      overlay: TrajectoryOverlay.fromJson(json['overlay']),
      metrics: DeliveryMetrics.fromJson(json['metrics']),
      imageWidth: width,
      imageHeight: height,
      warnings: [
        for (final v
            in diag['warnings'] is List ? diag['warnings'] as List : [])
          if (v is String && v.isNotEmpty) v[0].toUpperCase() + v.substring(1),
      ],
      json: json,
    );
  }
}

/// Why the server gave no call, and what to change, in the server's own words.
class NoCall {
  const NoCall({required this.code, required this.message, this.fix});

  final String? code;
  final String message;
  final String? fix;

  static NoCall? fromJson(Object? json) {
    if (json is! Map) return null;
    final message = json['message'];
    final fix = json['fix'];
    final code = json['code'];
    if (message is! String || message.isEmpty) return null;
    return NoCall(
      code: code is String ? code : null,
      message: message,
      fix: fix is String && fix.isNotEmpty ? fix : null,
    );
  }
}

/// Speed and spin shown as cards over the video.
class DeliveryMetrics {
  const DeliveryMetrics({
    required this.speedKmh,
    required this.speedMph,
    required this.spinDeg,
  });

  // null when not measured: speed too uncertain to show, spin with no bounce seen
  final double? speedKmh;
  final double? speedMph;
  final double? spinDeg;

  static DeliveryMetrics? fromJson(Object? json) {
    if (json is! Map) return null;
    final m = _map(json);
    return DeliveryMetrics(
      speedKmh: _readDouble(m, 'speed_kmh'),
      speedMph: _readDouble(m, 'speed_mph'),
      spinDeg: _readDouble(m, 'spin_deg'),
    );
  }
}

/// Pixel-space ball path overlay, projected server-side onto the analysed frame.
class TrajectoryOverlay {
  const TrajectoryOverlay({
    required this.path,
    required this.bounce,
    required this.impact,
    required this.strikerStumps,
    required this.corridor,
    required this.pitchRect,
  });

  /// Ordered ball path: real flight first, then the predicted continuation.
  final List<OverlayPoint> path;
  final OverlayPoint? bounce;
  final OverlayPoint? impact;
  final StumpLine? strikerStumps;
  final List<Offset> corridor;
  final List<Offset> pitchRect;

  static TrajectoryOverlay? fromJson(Object? json) {
    if (json is! Map) return null;
    final m = _map(json);
    final path = _points(m['path_px']);
    if (path.isEmpty) return null;
    return TrajectoryOverlay(
      path: path,
      bounce: OverlayPoint.fromJson(m['bounce_px']),
      impact: OverlayPoint.fromJson(m['impact_px']),
      strikerStumps: StumpLine.fromJson(_map(m['stumps_px'])['striker']),
      corridor: _offsets(m['corridor_px']),
      pitchRect: _offsets(m['pitch_rect_px']),
    );
  }
}

class OverlayPoint {
  const OverlayPoint({
    required this.tMs,
    required this.px,
    required this.predicted,
  });

  final int tMs;
  final Offset px;
  final bool predicted;

  static OverlayPoint? fromJson(Object? json) {
    final px = _offset(json);
    if (px == null) return null;
    final m = _map(json);
    return OverlayPoint(
      tMs: _readInt(m, 't_ms') ?? 0,
      px: px,
      predicted: m['phase'] == 'predicted',
    );
  }
}

class StumpLine {
  const StumpLine({required this.base, required this.top});

  final Offset base;
  final Offset top;

  static StumpLine? fromJson(Object? json) {
    final m = _map(json);
    final base = _offset(m['base']);
    final top = _offset(m['top']);
    if (base == null || top == null) return null;
    return StumpLine(base: base, top: top);
  }
}

/// The ball in metres: X along the pitch from the striker's stumps, Y across, Z up.
class WorldTrajectory {
  const WorldTrajectory({
    required this.points,
    required this.predictedToStumps,
  });

  final List<WorldPointM> points;
  final List<WorldPointM> predictedToStumps;

  static WorldTrajectory fromJson(Map<String, Object?> json) {
    List<WorldPointM> read(Object? list) => [
      if (list is List)
        for (final v in list) ?WorldPointM.fromJson(_map(v)),
    ];
    return WorldTrajectory(
      points: read(json['points_m']),
      predictedToStumps: read(json['predicted_to_stumps_m']),
    );
  }
}

class WorldPointM {
  const WorldPointM({
    required this.tMs,
    required this.x,
    required this.y,
    required this.z,
  });

  final int tMs;
  final double x;
  final double y;
  final double z;

  static WorldPointM? fromJson(Map<String, Object?> m) {
    final t = _readInt(m, 't_ms');
    final x = _readDouble(m, 'x');
    final y = _readDouble(m, 'y');
    final z = _readDouble(m, 'z');
    if (t == null || x == null || y == null || z == null) return null;
    return WorldPointM(tMs: t, x: x, y: y, z: z);
  }
}

class AnalysisEvents {
  const AnalysisEvents({required this.bounce, required this.impact});

  final EventPointM? bounce;
  final EventPointM? impact;

  static AnalysisEvents fromJson(Map<String, Object?> json) => AnalysisEvents(
    bounce: EventPointM.fromJson(json['bounce']),
    impact: EventPointM.fromJson(json['impact']),
  );
}

class EventPointM {
  const EventPointM({
    required this.tMs,
    required this.xM,
    required this.yM,
    this.zM,
  });

  final int tMs;
  final double xM;
  final double yM;
  final double? zM;

  static EventPointM? fromJson(Object? json) {
    final m = _map(json);
    final t = _readInt(m, 't_ms');
    final x = _readDouble(m, 'x_m');
    final y = _readDouble(m, 'y_m');
    if (t == null || x == null || y == null) return null;
    return EventPointM(tMs: t, xM: x, yM: y, zM: _readDouble(m, 'z_m'));
  }
}

enum LbwDecisionKey {
  out,
  notOut,
  umpiresCall,
  cantTell;

  // upper case from the result, lower case in the admin list's older rows
  static LbwDecisionKey? parse(Object? raw) =>
      switch (raw is String ? raw.toUpperCase() : null) {
        'OUT' => out,
        'NOT_OUT' => notOut,
        'UMPIRES_CALL' => umpiresCall,
        'CANT_TELL' => cantTell,
        _ => null,
      };
}

extension LbwDecisionLabel on LbwDecisionKey? {
  String get label => switch (this) {
    LbwDecisionKey.out => 'Out',
    LbwDecisionKey.notOut => 'Not out',
    LbwDecisionKey.umpiresCall => "Umpire's call",
    LbwDecisionKey.cantTell || null => 'No call',
  };
}

class LbwResult {
  const LbwResult({
    required this.decision,
    required this.reason,
    required this.pitchedInLine,
    required this.impactInLine,
    required this.wicketsHitting,
    required this.tones,
    required this.u95YM,
    required this.u95ZM,
    required this.confidence,
    required this.callStands,
  });

  final LbwDecisionKey? decision;
  final String reason;
  final bool pitchedInLine;
  final bool impactInLine;
  // null when the path never reached the stumps
  final bool? wicketsHitting;
  // each row's colour from the server: out, not_out or umpires_call
  final Map<String, Object?> tones;
  // how far the stump-plane crossing could be off, sideways and in height, 95 % of the time
  final double? u95YM;
  final double? u95ZM;
  // how sure the server is of an out or not out, 0..1
  final double? confidence;
  // the on-field call that stands, with umpire's call only
  final LbwDecisionKey? callStands;

  static LbwResult fromJson(Map<String, Object?> json) {
    final checks = _map(json['checks']);
    final pred = _map(json['prediction']);
    final reason = json['reason'];
    return LbwResult(
      decision: LbwDecisionKey.parse(json['verdict']),
      reason: reason is String ? reason.trim() : '',
      pitchedInLine: checks['pitching_in_line'] == true,
      impactInLine: checks['impact_in_line'] == true,
      wicketsHitting: switch (checks['wickets_hitting']) {
        final bool b => b,
        _ => null,
      },
      tones: _map(json['tones']),
      u95YM: _readDouble(pred, 'U95_y_m'),
      u95ZM: _readDouble(pred, 'U95_z_m'),
      confidence: _readDouble(json, 'confidence')?.clamp(0.0, 1.0),
      callStands: LbwDecisionKey.parse(json['call_stands']),
    );
  }
}

Map<String, Object?> _map(Object? v) =>
    v is Map ? v.cast<String, Object?>() : const {};

int? _readInt(Map<String, Object?> json, String key) {
  final v = json[key];
  return v is num && v.isFinite ? v.round() : null;
}

double? _readDouble(Map<String, Object?> json, String key) {
  final v = json[key];
  return v is num && v.isFinite ? v.toDouble() : null;
}

Offset? _offset(Object? json) {
  final m = _map(json);
  final u = _readDouble(m, 'u');
  final v = _readDouble(m, 'v');
  return u == null || v == null ? null : Offset(u, v);
}

List<Offset> _offsets(Object? json) => [
  if (json is List)
    for (final v in json) ?_offset(v),
];

List<OverlayPoint> _points(Object? json) => [
  if (json is List)
    for (final v in json) ?OverlayPoint.fromJson(v),
]..sort((a, b) => a.tMs.compareTo(b.tMs));
