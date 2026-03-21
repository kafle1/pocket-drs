import 'package:flutter_test/flutter_test.dart';
import 'package:pocket_drs/src/analysis/pitch_calibration.dart';
import 'package:pocket_drs/src/analysis/pitch_pose.dart';

void main() {
  group('PitchPoseEstimator', () {
    test('returns stable camera framing for valid normalized corners', () {
      const calibration = PitchCalibration(
        imagePoints: <Offset>[],
        imagePointsNorm: <Offset>[
          Offset(0.22, 0.30),
          Offset(0.78, 0.28),
          Offset(0.64, 0.82),
          Offset(0.36, 0.84),
        ],
      );

      final pose = PitchPoseEstimator.fromCalibration(calibration);

      expect(pose.yawDeg, inInclusiveRange(-80, 80));
      expect(pose.tiltDeg, inInclusiveRange(-35, 35));
      expect(pose.rollDeg, inInclusiveRange(-25, 25));
      expect(pose.cameraDistanceM, inInclusiveRange(10, 22));
      expect(pose.cameraHeightM, inInclusiveRange(1.2, 3.4));
      expect(pose.targetXM, inInclusiveRange(8.0, 10.06));
    });

    test('moves camera laterally with pitch center drift', () {
      const leftShifted = PitchCalibration(
        imagePoints: <Offset>[],
        imagePointsNorm: <Offset>[
          Offset(0.10, 0.28),
          Offset(0.60, 0.27),
          Offset(0.50, 0.80),
          Offset(0.22, 0.82),
        ],
      );
      const rightShifted = PitchCalibration(
        imagePoints: <Offset>[],
        imagePointsNorm: <Offset>[
          Offset(0.40, 0.28),
          Offset(0.90, 0.27),
          Offset(0.78, 0.80),
          Offset(0.50, 0.82),
        ],
      );

      final leftPose = PitchPoseEstimator.fromCalibration(leftShifted);
      final rightPose = PitchPoseEstimator.fromCalibration(rightShifted);

      expect(leftPose.cameraLateralOffsetM, lessThan(0));
      expect(rightPose.cameraLateralOffsetM, greaterThan(0));
    });

    test('brings camera closer when near edge dominates perspective', () {
      const flatterPerspective = PitchCalibration(
        imagePoints: <Offset>[],
        imagePointsNorm: <Offset>[
          Offset(0.28, 0.36),
          Offset(0.72, 0.36),
          Offset(0.66, 0.78),
          Offset(0.34, 0.78),
        ],
      );
      const strongerPerspective = PitchCalibration(
        imagePoints: <Offset>[],
        imagePointsNorm: <Offset>[
          Offset(0.18, 0.24),
          Offset(0.82, 0.24),
          Offset(0.60, 0.86),
          Offset(0.40, 0.86),
        ],
      );

      final flatterPose = PitchPoseEstimator.fromCalibration(flatterPerspective);
      final strongerPose = PitchPoseEstimator.fromCalibration(strongerPerspective);

      expect(strongerPose.cameraDistanceM, lessThan(flatterPose.cameraDistanceM));
      expect(strongerPose.targetXM, lessThanOrEqualTo(flatterPose.targetXM));
    });
  });
}
