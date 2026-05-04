import 'package:flutter/material.dart';

import '../analysis/pitch_calibration.dart';
import '../analysis/pitch_pose.dart';
import '../widgets/pitch_3d_viewer.dart';
import 'delivery_processing_screen.dart';

/// Shown right after calibration succeeds.  Confirms that the camera pose
/// is locked in, surfaces a quality hint, and offers a one-tap path into
/// delivery analysis without bouncing back to the pitch list.
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
      body: Stack(
        children: [
          Positioned.fill(
            child: Pitch3DViewer(
              showAnimation: false,
              pose: pose,
            ),
          ),
          Positioned.fill(
            child: DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [
                    Colors.black.withValues(alpha: 0.30),
                    Colors.black.withValues(alpha: 0.10),
                  ],
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                ),
              ),
            ),
          ),
          SafeArea(
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    children: [
                      const _StatusChip(),
                      const Spacer(),
                      IconButton(
                        onPressed: () => Navigator.of(context).pop(true),
                        icon: const Icon(Icons.close, color: Colors.white),
                        style: IconButton.styleFrom(
                          backgroundColor: Colors.white.withValues(alpha: 0.14),
                        ),
                      ),
                    ],
                  ),
                ),
                const Spacer(),
                Container(
                  width: double.infinity,
                  margin: const EdgeInsets.all(16),
                  padding: const EdgeInsets.all(22),
                  decoration: BoxDecoration(
                    color: theme.colorScheme.surface,
                    borderRadius: BorderRadius.circular(24),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withValues(alpha: 0.20),
                        blurRadius: 22,
                        offset: const Offset(0, 12),
                      ),
                    ],
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        pitchName,
                        style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'Pitch corners and stumps are locked in. Run an analysis on a delivery video to see the 3D ball trajectory and the LBW decision.',
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                      const SizedBox(height: 16),
                      const Row(
                        children: [
                          _Stat(label: 'Length', value: '20.12 m'),
                          SizedBox(width: 12),
                          _Stat(label: 'Width', value: '3.05 m'),
                          SizedBox(width: 12),
                          _Stat(label: 'Stumps', value: '0.71 m'),
                        ],
                      ),
                      const SizedBox(height: 22),
                      Row(
                        children: [
                          Expanded(
                            child: OutlinedButton.icon(
                              onPressed: () => Navigator.of(context).pop(true),
                              icon: const Icon(Icons.check),
                              label: const Text('Done'),
                              style: OutlinedButton.styleFrom(
                                padding: const EdgeInsets.symmetric(vertical: 16),
                              ),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: FilledButton.icon(
                              onPressed: () async {
                                // Pop this confirmation, then immediately push
                                // straight into the delivery flow on top of the
                                // pitch list so the user lands back at "Pitches"
                                // when they're done analyzing.
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
                              icon: const Icon(Icons.analytics_outlined),
                              label: const Text('Analyze now'),
                              style: FilledButton.styleFrom(
                                padding: const EdgeInsets.symmetric(vertical: 16),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip();
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.white.withValues(alpha: 0.18)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.check_circle, color: Color(0xFF4ADE80), size: 16),
          const SizedBox(width: 8),
          Text(
            'CALIBRATION SUCCESS',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: Colors.white,
              fontWeight: FontWeight.bold,
              letterSpacing: 0.8,
            ),
          ),
        ],
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: theme.textTheme.labelMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
            const SizedBox(height: 4),
            Text(value, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800)),
          ],
        ),
      ),
    );
  }
}
