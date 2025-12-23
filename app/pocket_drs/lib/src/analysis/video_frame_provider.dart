import 'dart:typed_data';

import 'package:video_thumbnail/video_thumbnail.dart';

/// Extracts decoded video frames as image bytes (JPEG/PNG) at requested timestamps.
///
/// This is slower than native OpenCV decoding but works cross-platform and is good
/// enough for short segments (1–2 seconds) on a student project timeline.
class VideoFrameProvider {
  VideoFrameProvider({required this.videoPath, this.maxCacheEntries = 24});

  final String videoPath;
  final int maxCacheEntries;

  // Map literals default to LinkedHashMap, preserving insertion order.
  final Map<int, Uint8List> _cache = <int, Uint8List>{};

  Future<Uint8List> getFrameJpeg({required int timeMs, int quality = 75}) async {
    final cached = _cache[timeMs];
    if (cached != null) return cached;

    final data = await VideoThumbnail.thumbnailData(
      video: videoPath,
      imageFormat: ImageFormat.JPEG,
      timeMs: timeMs,
      quality: quality,
    );

    if (data == null || data.isEmpty) {
      throw StateError('Failed to decode video frame at ${timeMs}ms');
    }

    _cache[timeMs] = data;
    if (_cache.length > maxCacheEntries) {
      _cache.remove(_cache.keys.first);
    }
    return data;
  }
}
