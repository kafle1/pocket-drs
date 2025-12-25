import 'package:flutter_test/flutter_test.dart';

import 'package:pocket_drs/src/api/analysis_result.dart';

void main() {
  test('LbwResult parses decision keys', () {
    final json = <String, Object?>{
      'likely_out': false,
      'checks': <String, Object?>{
        'pitching_in_line': true,
        'impact_in_line': true,
        'wickets_hitting': false,
      },
      'prediction': <String, Object?>{'y_at_stumps_m': 0.4},
      'decision': 'not_out',
      'reason': 'Missing stumps',
    };

    final lbw = LbwResult.fromJson(json);
    expect(lbw.decision, LbwDecisionKey.notOut);
    expect(lbw.wicketsHitting, false);
    expect(lbw.reason, contains('Missing'));
  });

  test('LbwResult rejects unknown decision', () {
    final json = <String, Object?>{
      'likely_out': false,
      'checks': <String, Object?>{
        'pitching_in_line': true,
        'impact_in_line': true,
        'wickets_hitting': false,
      },
      'prediction': <String, Object?>{'y_at_stumps_m': 0.4},
      'decision': 'NOT OUT',
      'reason': 'Missing stumps',
    };

    expect(() => LbwResult.fromJson(json), throwsA(isA<FormatException>()));
  });
}
