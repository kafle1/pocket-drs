import 'package:flutter/material.dart';

import '../analysis/pitch_calibration.dart';
import '../analysis/pitch_pose.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../widgets/drs_button.dart';
import '../widgets/pitch_3d_viewer.dart';
import 'delivery_processing_screen.dart';

/// Shown right after calibration succeeds. Confirms camera pose, surfaces a
/// telemetry summary, and offers a one-tap path into delivery analysis.
class PostCalibration3DScreen extends StatelessWidget {
  const PostCalibration3DScreen({
    super.key,
    required this.pitchId,
    required this.pitchName,
    required this.calibration,
  });

  final String pitchId;
  final String pitchName;
  final PitchCalibration calibration;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final pose = PitchPoseEstimator.fromCalibration(calibration);

    return Scaffold(
      backgroundColor: AppColors.inkBlack,
      body: Stack(
        children: [
          Positioned.fill(child: Pitch3DViewer(showAnimation: false, pose: pose)),
          IgnorePointer(
            child: DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [
                    AppColors.inkBlack.withValues(alpha: 0.55),
                    AppColors.inkBlack.withValues(alpha: 0),
                    AppColors.inkBlack.withValues(alpha: 0.70),
                  ],
                  stops: const [0, 0.45, 1],
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                ),
              ),
            ),
          ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.lg,
                AppSpacing.md,
                AppSpacing.lg,
                AppSpacing.xl,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: AppSpacing.md,
                          vertical: AppSpacing.sm,
                        ),
                        decoration: BoxDecoration(
                          color: AppColors.inkBlack.withValues(alpha: 0.7),
                          border: Border.all(
                            color: AppColors.bone.withValues(alpha: 0.2),
                            width: 1,
                          ),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Container(
                              width: 6,
                              height: 6,
                              decoration: const BoxDecoration(
                                color: AppColors.pitchGreen,
                                shape: BoxShape.circle,
                              ),
                            ),
                            const SizedBox(width: AppSpacing.sm),
                            Text(
                              'CALIBRATION LOCKED',
                              style: theme.textTheme.labelSmall?.copyWith(
                                color: AppColors.bone,
                              ),
                            ),
                          ],
                        ),
                      ),
                      const Spacer(),
                      Material(
                        color: AppColors.inkBlack.withValues(alpha: 0.7),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(AppRadius.sm),
                          side: BorderSide(
                            color: AppColors.bone.withValues(alpha: 0.2),
                            width: 1,
                          ),
                        ),
                        child: IconButton(
                          onPressed: () => Navigator.of(context).pop(true),
                          icon: const Icon(Icons.close, color: AppColors.bone, size: 18),
                        ),
                      ),
                    ],
                  ),
                  const Spacer(),
                  Text(
                    pitchName.toUpperCase(),
                    style: theme.textTheme.labelMedium?.copyWith(color: AppColors.ash),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    'Ready.',
                    style: theme.textTheme.displaySmall?.copyWith(color: AppColors.bone),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    'Pitch corners and stumps are locked. Run an analysis to see the 3D ball trajectory and the LBW decision.',
                    style: theme.textTheme.bodyMedium?.copyWith(color: AppColors.ash),
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  Container(height: 1, color: AppColors.bone.withValues(alpha: 0.15)),
                  const SizedBox(height: AppSpacing.lg),
                  const Row(
                    children: [
                      _Stat(label: 'PITCH-LEN', value: '20.12', unit: 'M'),
                      _Stat(label: 'PITCH-W', value: '3.05', unit: 'M'),
                      _Stat(label: 'STUMPS', value: '0.71', unit: 'M'),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.xl),
                  Row(
                    children: [
                      Expanded(
                        child: DrsButton(
                          label: 'DONE',
                          style: DrsButtonStyle.secondary,
                          icon: Icons.check,
                          onPressed: () => Navigator.of(context).pop(true),
                        ),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: DrsButton(
                          label: 'ANALYSE',
                          icon: Icons.bolt,
                          onPressed: () async {
                            Navigator.of(context).pop(true);
                            await Navigator.of(context).push(
                              MaterialPageRoute(
                                builder: (_) => DeliveryProcessingScreen(
                                  pitchId: pitchId,
                                  pitchName: pitchName,
                                ),
                              ),
                            );
                          },
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value, required this.unit});
  final String label;
  final String value;
  final String unit;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: theme.textTheme.labelSmall?.copyWith(color: AppColors.ash),
          ),
          const SizedBox(height: AppSpacing.xs),
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Text(
                value,
                style: AppTypography.mono(theme.textTheme.headlineMedium)?.copyWith(
                  color: AppColors.bone,
                ),
              ),
              const SizedBox(width: 3),
              Text(
                unit,
                style: theme.textTheme.labelSmall?.copyWith(color: AppColors.ash),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
