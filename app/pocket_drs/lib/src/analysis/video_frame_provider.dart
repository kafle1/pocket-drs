import 'dart:async';
import 'dart:typed_data';

import 'frame_decoder.dart';

abstract class FrameProvider {
  Future<Uint8List> getFrameJpeg({required int timeMs, int quality});
}

typedef FrameDecodeFn = Future<Uint8List?> Function({
  required String videoPath,
  required int timeMs,
  required int quality,
});

/// Extracts decoded video frames as image bytes (JPEG/PNG) at requested timestamps.
///
/// This is slower than native OpenCV decoding but works cross-platform and is good
/// enough for short segments (1–2 seconds) on a student project timeline.
class VideoFrameProvider implements FrameProvider {
  VideoFrameProvider({
    required this.videoPath,
    this.maxCacheEntries = 24,
    FrameDecodeFn? decode,
  }) : _decode = decode ?? _defaultDecode;

  final String videoPath;
  final int maxCacheEntries;

  final FrameDecodeFn _decode;

  // Map literals default to LinkedHashMap, preserving insertion order.
  final Map<int, Uint8List> _cache = <int, Uint8List>{};
  final Map<int, Future<Uint8List>> _inFlight = <int, Future<Uint8List>>{};

  // Serialize decode requests to avoid exhausting Android's ImageReader buffers
  // when multiple frame fetches are triggered in quick succession (e.g., slider scrubbing).
  Future<void> _decodeChain = Future<void>.value();

  bool _disposed = false;

  static Future<Uint8List?> _defaultDecode({
    required String videoPath,
    required int timeMs,
    required int quality,
  }) {
    return decodeFrameJpeg(videoPath: videoPath, timeMs: timeMs, quality: quality);
  }

  /// Wait for any queued decode work to complete.
  ///
  /// Useful to avoid overlapping MediaCodec/MediaMetadataRetriever work
  /// between screens.
  Future<void> waitForIdle() => _decodeChain;

  void dispose() {
    _disposed = true;
    _cache.clear();
    _inFlight.clear();

    // Web-only: drop any associated video element/canvas (no-op on io).
    releaseWebFrameDecoder(videoPath);
  }

  @override
  Future<Uint8List> getFrameJpeg({required int timeMs, int quality = 75}) async {
    if (_disposed) {
      throw StateError('VideoFrameProvider is disposed');
    }

    if (timeMs < 0) {
      throw ArgumentError.value(timeMs, 'timeMs', 'must be >= 0');
    }

    final safeQuality = quality.clamp(1, 100);

    final cached = _cache[timeMs];
    if (cached != null) return cached;

    final inFlight = _inFlight[timeMs];
    if (inFlight != null) return inFlight;

    final future = _enqueueDecode(timeMs: timeMs, quality: safeQuality);
    _inFlight[timeMs] = future;
    return future.whenComplete(() => _inFlight.remove(timeMs));
  }

  Future<Uint8List> _enqueueDecode({required int timeMs, required int quality}) {
    final task = _decodeChain.then((_) => _decodeWithRetries(timeMs: timeMs, quality: quality));

    // Keep the chain alive even if a decode fails.
    _decodeChain = task.then((_) {}, onError: (_) {});

    return task.then((data) {
      if (!_disposed) {
        _cache[timeMs] = data;
        if (_cache.length > maxCacheEntries) {
          _cache.remove(_cache.keys.first);
        }
      }
      return data;
    });
  }

  Future<Uint8List> _decodeWithRetries({required int timeMs, required int quality}) async {
    if (_disposed) {
      throw StateError('VideoFrameProvider is disposed');
    }

    // Delay moved to frame_decoder_io for global serialization.
    const maxRetries = 3;
    for (var attempt = 0; attempt < maxRetries; attempt++) {
      if (_disposed) {
        throw StateError('VideoFrameProvider is disposed');
      }
      try {
        final data = await _decode(videoPath: videoPath, timeMs: timeMs, quality: quality);
        if (data != null && data.isNotEmpty) {
          return data;
        }
      } catch (_) {
        // Retry below.
      }

      // Exponential backoff: 100ms, 200ms, 400ms.
      await Future.delayed(Duration(milliseconds: 100 << attempt));
    }

    throw StateError('Failed to decode video frame at ${timeMs}ms');
  }
}
