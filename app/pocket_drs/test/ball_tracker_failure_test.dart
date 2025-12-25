import 'package:flutter_test/flutter_test.dart';
import 'package:pocket_drs/src/api/analysis_result.dart';

void main() {
  test('AnalysisResult parses server response', () {
    final json = <String, Object?>{
      'image_size': <String, Object?>{'width': 1920, 'height': 1080},
      'track': <String, Object?>{
        'points': [
          <String, Object?>{'t_ms': 0, 'x_px': 100.0, 'y_px': 200.0, 'confidence': 0.9},
          <String, Object?>{'t_ms': 33, 'x_px': 110.0, 'y_px': 205.0, 'confidence': 0.8},
        ],
      },
      'pitch_plane': <String, Object?>{
        'points_m': [
          <String, Object?>{'t_ms': 0, 'x_m': 10.0, 'y_m': 0.02},
          <String, Object?>{'t_ms': 33, 'x_m': 9.8, 'y_m': 0.025},
        ],
      },
      'events': <String, Object?>{
        'bounce': <String, Object?>{'index': 0, 'confidence': 0.7},
        'impact': <String, Object?>{'index': 1, 'confidence': 0.8},
      },
      'lbw': <String, Object?>{
        'likely_out': true,
        'checks': <String, Object?>{
          'pitching_in_line': true,
          'impact_in_line': true,
          'wickets_hitting': true,
        },
        'prediction': <String, Object?>{'y_at_stumps_m': 0.01},
        'decision': 'out',
        'reason': 'Hitting stumps',
      },
      'diagnostics': <String, Object?>{
        'warnings': ['tracker_low_confidence'],
        'log_id': null,
      },
    };

    final parsed = AnalysisResult.fromServerJson(json);
    expect(parsed.track.width, 1920);
    expect(parsed.track.height, 1080);
    expect(parsed.track.points.length, 2);
    expect(parsed.pitchPlane.length, 2);
    expect(parsed.events?.bounceIndex, 0);
    expect(parsed.lbw?.decision, LbwDecisionKey.out);
    expect(parsed.warnings, contains('tracker_low_confidence'));
  });
}
