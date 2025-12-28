import 'dart:async';
import 'dart:typed_data';

import 'package:video_thumbnail/video_thumbnail.dart';

/// Global serialization lock for frame extraction on Android/iOS.
///
/// `video_thumbnail` ultimately goes through platform decoders (MediaCodec /
/// MediaMetadataRetriever). Running multiple extractions in parallel can exhaust
/// ImageReader buffers and flood logs with:
/// `ImageReader_JNI: Unable to acquire a buffer item...`.
Future<void> _globalDecodeChain = Future<void>.value();

Future<T> _runSerialized<T>(Future<T> Function() op) {
  final completer = Completer<T>();

  // Ensure a previous failure doesn't poison the chain.
  final scheduled = _globalDecodeChain.catchError((_) {}).then((_) async {
    try {
      completer.complete(await op());
    } catch (e, st) {
      completer.completeError(e, st);
    }
  });

  // Keep chain alive regardless of this op outcome.
  _globalDecodeChain = scheduled.then((_) {}, onError: (_) {});

  return completer.future;
}

Future<Uint8List?> decodeFrameJpeg({
  required String videoPath,
  required int timeMs,
  required int quality,
}) {
  final safeQuality = quality.clamp(1, 100);

  return _runSerialized(() async {
    // Aggressive delay prevents Android decoder buffer exhaustion.
    // video_thumbnail uses MediaCodec/MediaMetadataRetriever which share
    // limited ImageReader buffer pools with video playback.
    await Future<void>.delayed(const Duration(milliseconds: 100));
    return VideoThumbnail.thumbnailData(
      video: videoPath,
      imageFormat: ImageFormat.JPEG,
      timeMs: timeMs,
      quality: safeQuality,
    );
  });
}

// Web-only implementation keeps a cached VideoElement/Canvas; on non-web this is a no-op.
void releaseWebFrameDecoder(String videoPath) {}
