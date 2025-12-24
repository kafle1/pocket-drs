import 'package:flutter_test/flutter_test.dart';
import 'package:pocket_drs/src/analysis/homography.dart';

void main() {
  test('Homography maps 4 points exactly (within tolerance)', () {
    final src = <Offset>[
      const Offset(0, 0),
      const Offset(100, 0),
      const Offset(100, 50),
      const Offset(0, 50),
    ];
    final dst = <Offset>[
      const Offset(0, 0),
      const Offset(0, 3.05),
      const Offset(20.12, 3.05),
      const Offset(20.12, 0),
    ];

    final H = Homography.fromFourPoints(src: src, dst: dst);

    for (var i = 0; i < 4; i++) {
      final p = H.transform(src[i]);
      expect(p.dx, closeTo(dst[i].dx, 1e-6));
      expect(p.dy, closeTo(dst[i].dy, 1e-6));
    }
  });

  test('Homography throws on singular configuration', () {
    final src = <Offset>[
      const Offset(0, 0),
      const Offset(1, 0),
      const Offset(2, 0),
      const Offset(3, 0),
    ];
    final dst = <Offset>[
      const Offset(0, 0),
      const Offset(1, 0),
      const Offset(2, 0),
      const Offset(3, 0),
    ];

    expect(
      () => Homography.fromFourPoints(src: src, dst: dst),
      throwsA(isA<StateError>()),
    );
  });
}
