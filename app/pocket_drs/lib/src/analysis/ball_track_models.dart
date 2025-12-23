import 'dart:ui';

class BallTrackPoint {
  const BallTrackPoint({required this.t, required this.p, required this.confidence});

  /// Timestamp (ms from start of the *video*, not the segment).
  final int t;

  /// Ball center in image coordinates (pixels).
  final Offset p;

  /// 0..1 heuristic confidence.
  final double confidence;
}

class BallTrackResult {
  const BallTrackResult({required this.points, required this.width, required this.height});

  final List<BallTrackPoint> points;
  final int width;
  final int height;
}

class BallTrackRequest {
  const BallTrackRequest({
    required this.videoPath,
    required this.startMs,
    required this.endMs,
    required this.sampleFps,
    required this.initialBallPixel,
    required this.searchRadiusPx,
  });

  final String videoPath;
  final int startMs;
  final int endMs;

  /// Sampling rate used for analysis (not necessarily video FPS).
  final int sampleFps;

  /// If provided, we build a color signature from that pixel in the first frame.
  /// Use Offset(-1, -1) to indicate "not set" (compute() payload must be JSON-ish).
  final Offset initialBallPixel;

  /// Search window radius around predicted position.
  final int searchRadiusPx;
}
