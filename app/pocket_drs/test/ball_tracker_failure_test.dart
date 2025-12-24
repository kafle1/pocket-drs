import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:pocket_drs/src/analysis/ball_track_models.dart';
import 'package:pocket_drs/src/analysis/ball_tracker.dart';
import 'package:pocket_drs/src/analysis/video_frame_provider.dart';

class _FakeFrameProvider implements FrameProvider {
  _FakeFrameProvider({required this.frames, this.failAt = const {}});

  final Map<int, img.Image> frames;
  final Set<int> failAt;

  @override
  Future<Uint8List> getFrameJpeg({required int timeMs, int quality = 75}) async {
    if (failAt.contains(timeMs)) {
      throw StateError('fail at $timeMs');
    }
    final frame = frames[timeMs];
    if (frame == null) {
      throw StateError('missing frame $timeMs');
    }
    return Uint8List.fromList(img.encodeJpg(frame, quality: quality));
  }
}

img.Image _solidFrame(int r, int g, int b) {
  final image = img.Image(width: 4, height: 4);
  for (var y = 0; y < image.height; y++) {
    for (var x = 0; x < image.width; x++) {
      image.setPixelRgba(x, y, r, g, b, 255);
    }
  }
  return image;
}

void main() {
  test('BallTracker skips frames that fail to decode', () async {
    final frames = <int, img.Image>{
      0: _solidFrame(255, 0, 0),
      33: _solidFrame(0, 255, 0),
      66: _solidFrame(0, 0, 255),
      99: _solidFrame(255, 255, 0),
    };

    final provider = _FakeFrameProvider(frames: frames, failAt: {33});
    final req = BallTrackRequest(
      videoPath: 'fake.mp4',
      startMs: 0,
      endMs: 99,
      sampleFps: 30,
      initialBallPixel: const Offset(2, 2),
      searchRadiusPx: 8,
    );

    final result = await trackInSameIsolateForTest(req, provider);

    expect(result.points, isNotEmpty);
    expect(result.width, equals(4));
    expect(result.height, equals(4));
  });
}
