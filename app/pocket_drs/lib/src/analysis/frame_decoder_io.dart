import 'dart:async';
import 'dart:typed_data';

import 'package:video_thumbnail/video_thumbnail.dart';

import '../utils/native_video_resources.dart';

/// Global serialization lock for frame extraction on Android/iOS.
///
/// `video_thumbnail` ultimately goes through platform decoders (MediaCodec /
/// MediaMetadataRetriever). Running multiple extractions in parallel can exhaust
/// ImageReader buffers and flood logs with:
/// `ImageReader_JNI: Unable to acquire a buffer item...`.
Future<Uint8List?> decodeFrameJpeg({
  required String videoPath,
  required int timeMs,
  required int quality,
}) {
  final safeQuality = quality.clamp(1, 100);

  return runWithNativeVideoResources(() async {
    // Give Android enough time to recycle decoder-backed buffers before frame extraction.
    await coolDownNativeVideoResources(delay: const Duration(milliseconds: 500));
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
