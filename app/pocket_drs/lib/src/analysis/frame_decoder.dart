import 'dart:typed_data';

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
