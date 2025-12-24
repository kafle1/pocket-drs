import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:pocket_drs/src/analysis/video_frame_provider.dart';

void main() {
  test('VideoFrameProvider dedupes in-flight requests for same timestamp', () async {
    var calls = 0;
    final provider = VideoFrameProvider(
      videoPath: '/fake.mp4',
      decode: ({required videoPath, required timeMs, required quality}) async {
        calls++;
        await Future<void>.delayed(const Duration(milliseconds: 20));
        return Uint8List.fromList(<int>[timeMs % 256]);
      },
    );

    final a = provider.getFrameJpeg(timeMs: 1000, quality: 90);
    final b = provider.getFrameJpeg(timeMs: 1000, quality: 90);

    final ra = await a;
    final rb = await b;

    expect(calls, 1);
    expect(ra, rb);
  });

  test('VideoFrameProvider serializes decode work across timestamps', () async {
    var active = 0;
    var maxActive = 0;

    final provider = VideoFrameProvider(
      videoPath: '/fake.mp4',
      decode: ({required videoPath, required timeMs, required quality}) async {
        active++;
        if (active > maxActive) maxActive = active;
        await Future<void>.delayed(const Duration(milliseconds: 15));
        active--;
        return Uint8List.fromList(<int>[timeMs % 256]);
      },
    );

    final futures = <Future<Uint8List>>[
      provider.getFrameJpeg(timeMs: 0),
      provider.getFrameJpeg(timeMs: 33),
      provider.getFrameJpeg(timeMs: 66),
      provider.getFrameJpeg(timeMs: 99),
    ];

    await Future.wait(futures);

    expect(maxActive, 1);
  });

  test('VideoFrameProvider throws after dispose', () async {
    final provider = VideoFrameProvider(
      videoPath: '/fake.mp4',
      decode: ({required videoPath, required timeMs, required quality}) async {
        return Uint8List.fromList(<int>[1, 2, 3]);
      },
    );

    provider.dispose();

    await expectLater(
      () => provider.getFrameJpeg(timeMs: 0),
      throwsA(isA<StateError>()),
    );
  });

  test('VideoFrameProvider waitForIdle completes when queue drains', () async {
    final gate = Completer<void>();

    final provider = VideoFrameProvider(
      videoPath: '/fake.mp4',
      decode: ({required videoPath, required timeMs, required quality}) async {
        await gate.future;
        return Uint8List.fromList(<int>[timeMs % 256]);
      },
    );

    final f1 = provider.getFrameJpeg(timeMs: 0);
    final idle = provider.waitForIdle();

    final first = await Future.any<String>([
      idle.then((_) => 'idle'),
      Future<String>.delayed(const Duration(milliseconds: 10), () => 'timeout'),
    ]);
    expect(first, 'timeout');

    gate.complete();
    await f1;
    await idle;
  });
}
