import 'dart:typed_data';

import 'package:video_thumbnail/video_thumbnail.dart';

Future<Uint8List?> decodeFrameJpeg({
  required String videoPath,
  required int timeMs,
  required int quality,
}) {
  return VideoThumbnail.thumbnailData(
    video: videoPath,
    imageFormat: ImageFormat.JPEG,
    timeMs: timeMs,
    quality: quality,
  );
}

// Web-only implementation keeps a cached VideoElement/Canvas; on non-web this is a no-op.
void releaseWebFrameDecoder(String videoPath) {}
