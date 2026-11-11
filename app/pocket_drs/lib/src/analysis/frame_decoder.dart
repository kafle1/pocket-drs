import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:video_thumbnail/video_thumbnail.dart';

import '../utils/native_video_resources.dart';

Future<Uint8List?> decodeFrameJpeg({
  required String videoPath,
  required int timeMs,
}) {
  return runWithNativeVideoResources(() async {
    // give android time to recycle the last decoder's buffers
    await Future<void>.delayed(const Duration(milliseconds: 500));
    return VideoThumbnail.thumbnailData(
      video: videoPath,
      imageFormat: ImageFormat.JPEG,
      timeMs: timeMs,
      quality: 95,
    );
  });
}

/// How far the picture moved between [startMs] and [endMs], as the largest shift of the whole
/// frame against the first one, in frame widths; null when the frames can't be read.
Future<double?> cameraShake({
  required String videoPath,
  required int startMs,
  required int endMs,
}) async {
  const w = 96, reach = 6;
  final frames = <(Uint8List, int)>[];
  for (var i = 0; i < 4; i++) {
    final jpg = await decodeFrameJpeg(
      videoPath: videoPath,
      timeMs: startMs + (endMs - startMs) * i ~/ 3,
    );
    if (jpg == null) return null;
    final codec = await ui.instantiateImageCodec(jpg, targetWidth: w);
    final image = (await codec.getNextFrame()).image;
    final rgba = await image.toByteData();
    final h = image.height;
    image.dispose();
    codec.dispose();
    if (rgba == null) return null;
    final luma = Uint8List(w * h);
    for (var p = 0; p < luma.length; p++) {
      luma[p] =
          (rgba.getUint8(p * 4) * 3 +
              rgba.getUint8(p * 4 + 1) * 6 +
              rgba.getUint8(p * 4 + 2)) ~/
          10;
    }
    frames.add((luma, h));
  }
  final (ref, h) = frames.first;
  var worst = 0.0;
  for (final (f, fh) in frames.skip(1)) {
    if (fh != h) return null;
    // the shift that lines the frame up best; players and the ball are too small to sway it
    var best = double.infinity;
    var bestShift = 0.0;
    for (var dy = -reach; dy <= reach; dy++) {
      for (var dx = -reach; dx <= reach; dx++) {
        var sum = 0, n = 0;
        for (var y = reach; y < h - reach; y += 2) {
          for (var x = reach; x < w - reach; x += 2) {
            sum += (ref[y * w + x] - f[(y + dy) * w + x + dx]).abs();
            n++;
          }
        }
        final cost = n == 0 ? double.infinity : sum / n;
        if (cost < best) {
          best = cost;
          bestShift = math.sqrt(dx * dx + dy * dy.toDouble());
        }
      }
    }
    worst = math.max(worst, bestShift / w);
  }
  return worst;
}
