import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;

class _WebVideoContext {
  _WebVideoContext(this.video, this.canvas, this.ctx);

  final html.VideoElement video;
  final html.CanvasElement canvas;
  final html.CanvasRenderingContext2D ctx;

  bool disposed = false;

  Future<void> ensureLoaded() async {
    if (disposed) throw StateError('WebVideoContext disposed');

    if (video.readyState >= 1 && (video.duration.isFinite)) {
      return;
    }

    // Load metadata.
    final completer = Completer<void>();
    late html.EventListener onMeta;
    late html.EventListener onErr;

    onMeta = (_) {
      video.removeEventListener('loadedmetadata', onMeta);
      video.removeEventListener('error', onErr);
      if (!completer.isCompleted) completer.complete();
    };

    onErr = (_) {
      video.removeEventListener('loadedmetadata', onMeta);
      video.removeEventListener('error', onErr);
      if (!completer.isCompleted) {
        completer.completeError(StateError('Failed to load video metadata'));
      }
    };

    video.addEventListener('loadedmetadata', onMeta);
    video.addEventListener('error', onErr);
    video.load();

    return completer.future;
  }

  Future<void> seekToSeconds(double seconds) async {
    if (disposed) throw StateError('WebVideoContext disposed');
    await ensureLoaded();

    final completer = Completer<void>();
    late html.EventListener onSeek;
    late html.EventListener onErr;

    onSeek = (_) {
      video.removeEventListener('seeked', onSeek);
      video.removeEventListener('error', onErr);
      if (!completer.isCompleted) completer.complete();
    };

    onErr = (_) {
      video.removeEventListener('seeked', onSeek);
      video.removeEventListener('error', onErr);
      if (!completer.isCompleted) {
        completer.completeError(StateError('Failed to seek video'));
      }
    };

    video.addEventListener('seeked', onSeek);
    video.addEventListener('error', onErr);

    // Clamp within duration when known.
    final d = video.duration;
    if (d.isFinite) {
      seconds = seconds.clamp(0.0, d).toDouble();
    } else {
      seconds = seconds < 0 ? 0 : seconds;
    }

    video.currentTime = seconds;
    return completer.future;
  }

  Uint8List snapshotJpegBytes({required int quality}) {
    if (disposed) throw StateError('WebVideoContext disposed');

    // Size canvas to the actual video resolution.
    final w = video.videoWidth;
    final h = video.videoHeight;
    if (w <= 0 || h <= 0) {
      throw StateError('Video not ready (missing dimensions)');
    }

    canvas.width = w;
    canvas.height = h;
    ctx.drawImageScaled(video, 0, 0, w, h);

    // quality: 0..100 -> 0..1
    final q = (quality.clamp(1, 100)) / 100.0;
    final dataUrl = canvas.toDataUrl('image/jpeg', q);
    final comma = dataUrl.indexOf(',');
    if (comma < 0) throw StateError('Failed to encode JPEG');
    final b64 = dataUrl.substring(comma + 1);
    return base64Decode(b64);
  }

  void dispose() {
    disposed = true;
    // Help GC.
    video.src = '';
  }
}

final Map<String, _WebVideoContext> _contexts = <String, _WebVideoContext>{};

_WebVideoContext _getContext(String videoPath) {
  final existing = _contexts[videoPath];
  if (existing != null && !existing.disposed) return existing;

  final video = html.VideoElement()
    ..src = videoPath
    ..preload = 'auto'
    ..muted = true
    ..crossOrigin = 'anonymous';

  // Hint for iOS Safari (attribute form; dart:html doesn't expose playsInline).
  video.setAttribute('playsinline', 'true');

  final canvas = html.CanvasElement();
  final ctx = canvas.context2D;
  final c = _WebVideoContext(video, canvas, ctx);
  _contexts[videoPath] = c;
  return c;
}

Future<Uint8List?> decodeFrameJpeg({
  required String videoPath,
  required int timeMs,
  required int quality,
}) async {
  final ctx = _getContext(videoPath);
  await ctx.seekToSeconds(timeMs / 1000.0);
  final bytes = ctx.snapshotJpegBytes(quality: quality);
  return bytes;
}

void releaseWebFrameDecoder(String videoPath) {
  final ctx = _contexts.remove(videoPath);
  ctx?.dispose();
}
