import 'package:flutter_test/flutter_test.dart';
import 'package:pocket_drs/src/api/analysis_result.dart';

void main() {
  group('AnalysisResult.fromServerJson', () {
    test('reconstructs pitch-plane points from homography when server omits them', () {
      final result = AnalysisResult.fromServerJson(<String, Object?>{
        'image_size': <String, Object?>{'width': 1080, 'height': 1920},
        'track': <String, Object?>{
          'points': <Object?>[
            <String, Object?>{'t_ms': 1000, 'x_px': 18.0, 'y_px': 0.2, 'confidence': 0.9},
            <String, Object?>{'t_ms': 1016, 'x_px': 16.6, 'y_px': 0.1, 'confidence': 0.88},
            <String, Object?>{'t_ms': 1032, 'x_px': 15.1, 'y_px': -0.1, 'confidence': 0.86},
            <String, Object?>{'t_ms': 1048, 'x_px': 13.7, 'y_px': -0.2, 'confidence': 0.84},
          ],
        },
        'calibration': <String, Object?>{
          'mode': 'taps',
          'homography': <String, Object?>{
            'matrix': <Object?>[
              <Object?>[1.0, 0.0, 0.0],
              <Object?>[0.0, 1.0, 0.0],
              <Object?>[0.0, 0.0, 1.0],
            ],
          },
        },
        'pitch_plane': null,
        'events': <String, Object?>{
          'bounce': <String, Object?>{'index': 1, 'confidence': 0.7},
          'impact': <String, Object?>{'index': 3, 'confidence': 0.6},
        },
        'lbw': null,
        'diagnostics': <String, Object?>{'warnings': <Object?>[]},
      });

      expect(result.pitchPlane, hasLength(4));
      expect(result.pitchPlane.first.worldM.dx, closeTo(18.0, 1e-9));
      expect(result.pitchPlane.last.worldM.dx, closeTo(13.7, 1e-9));
      expect(
        result.warnings,
        contains('Recovered pitch-plane points from calibration homography.'),
      );
    });
  });
}
