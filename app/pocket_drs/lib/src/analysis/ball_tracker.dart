import 'dart:ui';

import 'package:flutter/foundation.dart';
import 'package:image/image.dart' as img;

import '../utils/analysis_logger.dart';
import 'ball_track_models.dart';
import 'kalman_2d.dart';
import 'video_frame_provider.dart';

class BallTracker {
  const BallTracker();

  Future<BallTrackResult> track(BallTrackRequest req) async {
    await AnalysisLogger.instance.log(
      'track start video=${req.videoPath} range=${req.startMs}-${req.endMs} seed=(${req.initialBallPixel.dx},${req.initialBallPixel.dy}) fps=${req.sampleFps}',
    );
    try {
      final res = await compute(_trackInIsolate, req);
      await AnalysisLogger.instance.log(
        'track success points=${res.points.length} size=${res.width}x${res.height}',
      );
      return res;
    } catch (e) {
      await AnalysisLogger.instance.log('track failed: $e');
      rethrow;
    }
  }
}

Future<BallTrackResult> _trackInIsolate(BallTrackRequest req) async {
  final provider = VideoFrameProvider(videoPath: req.videoPath);
  return _track(req, provider);
}

@visibleForTesting
Future<BallTrackResult> trackInSameIsolateForTest(
  BallTrackRequest req,
  FrameProvider provider,
) {
  return _track(req, provider);
}

Future<BallTrackResult> _track(BallTrackRequest req, FrameProvider provider) async {
  final dtMs = (1000 / req.sampleFps).round().clamp(1, 1000);
  final times = <int>[];
  for (var t = req.startMs; t <= req.endMs; t += dtMs) {
    times.add(t);
  }

  // Decode first frame to set size and optional color signature.
  final firstBytes = await _safeFrame(provider, times.first);
  if (firstBytes == null) {
    throw StateError('Failed to decode first frame at ${times.first}ms');
  }
  final firstImage = img.decodeImage(firstBytes);
  if (firstImage == null) {
    throw StateError('Failed to decode first frame');
  }
  final width = firstImage.width;
  final height = firstImage.height;

  final hasSeed = req.initialBallPixel.dx >= 0 && req.initialBallPixel.dy >= 0;
  final seed = hasSeed
      ? _clampOffset(req.initialBallPixel, width: width, height: height)
      : null;

  final colorSig = seed != null
      ? _ColorSignature.fromImage(firstImage, seed)
      : null;

  // Tracking.
  Kalman2D? kf;
  Offset? prevMeas;
  img.Image? prevFrameGray;

  final out = <BallTrackPoint>[];
  for (var i = 0; i < times.length; i++) {
    final t = times[i];
    final bytes = i == 0 ? firstBytes : await _safeFrame(provider, t);
    if (bytes == null) continue;
    final frame = i == 0 ? firstImage : img.decodeImage(bytes);
    if (frame == null) continue;

    final gray = img.grayscale(frame);
    final predicted = kf?.position;
    final measurement = _detectBall(
      frame: frame,
      gray: gray,
      prevGray: prevFrameGray,
      predicted: predicted,
      searchRadiusPx: req.searchRadiusPx,
      colorSig: colorSig,
    );

    // Initialize filter when we get the first measurement.
    if (kf == null && measurement != null) {
      kf = Kalman2D(initialPosition: measurement);
    }

    final dt = i == 0 ? 1.0 / req.sampleFps : dtMs / 1000.0;
    kf?.predict(dt);

    if (measurement != null && kf != null) {
      kf.update(measurement);
      prevMeas = measurement;
    }

    final pos = kf?.position ?? prevMeas;
    if (pos != null) {
      final conf = measurement != null ? 1.0 : 0.35;
      out.add(BallTrackPoint(t: t, p: pos, confidence: conf));
    }
    prevFrameGray = gray;
  }

  return BallTrackResult(points: out, width: width, height: height);
}

Future<Uint8List?> _safeFrame(FrameProvider provider, int timeMs) async {
  try {
    return await provider.getFrameJpeg(timeMs: timeMs, quality: 90);
  } catch (_) {
    return null;
  }
}

Offset _clampOffset(Offset p, {required int width, required int height}) {
  final x = p.dx.clamp(0.0, (width - 1).toDouble()).toDouble();
  final y = p.dy.clamp(0.0, (height - 1).toDouble()).toDouble();
  return Offset(x, y);
}

class _ColorSignature {
  _ColorSignature({required this.r, required this.g, required this.b});

  final double r;
  final double g;
  final double b;

  static _ColorSignature fromImage(img.Image image, Offset seed) {
    final x = seed.dx.round().clamp(0, image.width - 1);
    final y = seed.dy.round().clamp(0, image.height - 1);
    final px = image.getPixel(x, y);
    return _ColorSignature(
      r: px.r.toDouble(),
      g: px.g.toDouble(),
      b: px.b.toDouble(),
    );
  }

  bool closeTo(img.Pixel p, {double tol = 55}) {
    final dr = (p.r - r).abs();
    final dg = (p.g - g).abs();
    final db = (p.b - b).abs();
    return dr + dg + db < tol * 3;
  }
}

Offset? _detectBall({
  required img.Image frame,
  required img.Image gray,
  required img.Image? prevGray,
  required Offset? predicted,
  required int searchRadiusPx,
  required _ColorSignature? colorSig,
}) {
  final w = frame.width;
  final h = frame.height;

  // Search region: full frame initially, then tighten around prediction.
  final center = predicted ?? const Offset(-1, -1);
  final hasPred = predicted != null;
  final x0 = hasPred ? (center.dx - searchRadiusPx).round() : 0;
  final y0 = hasPred ? (center.dy - searchRadiusPx).round() : 0;
  final x1 = hasPred ? (center.dx + searchRadiusPx).round() : (w - 1);
  final y1 = hasPred ? (center.dy + searchRadiusPx).round() : (h - 1);

  final rx0 = x0.clamp(0, w - 1);
  final ry0 = y0.clamp(0, h - 1);
  final rx1 = x1.clamp(0, w - 1);
  final ry1 = y1.clamp(0, h - 1);

  // 1) Color-based centroid (fast, works well for distinct ball colors).
  if (colorSig != null) {
    int n = 0;
    double sx = 0;
    double sy = 0;
    for (var y = ry0; y <= ry1; y++) {
      for (var x = rx0; x <= rx1; x++) {
        final p = frame.getPixel(x, y);
        if (colorSig.closeTo(p)) {
          n++;
          sx += x;
          sy += y;
        }
      }
    }
    if (n >= 20) {
      return Offset(sx / n, sy / n);
    }
  }

  // 2) Motion-based detection (difference from previous grayscale).
  if (prevGray != null) {
    final thr = 22; // tuned for daylight + 8-bit grayscale
    // Find brightest moving blob center using weighted centroid.
    double sx = 0;
    double sy = 0;
    double sw = 0;
    for (var y = ry0; y <= ry1; y++) {
      for (var x = rx0; x <= rx1; x++) {
        final a = gray.getPixel(x, y);
        final b = prevGray.getPixel(x, y);
        final da = (a.r - b.r).abs();
        if (da > thr) {
          final wgt = da.toDouble();
          sw += wgt;
          sx += x * wgt;
          sy += y * wgt;
        }
      }
    }
    if (sw > 3000) {
      return Offset(sx / sw, sy / sw);
    }
  }

  // 3) If we have a prediction but no detection, keep tracking by prediction.
  return null;
}
