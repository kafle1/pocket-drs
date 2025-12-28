import 'package:flutter/material.dart';
import '../analysis/pitch_calibration.dart';
import '../widgets/pitch_3d_viewer.dart';

class PostCalibration3DScreen extends StatelessWidget {
  const PostCalibration3DScreen({
    super.key,
    required this.pitchName,
    required this.calibration,
  });

  final String pitchName;
  final PitchCalibration calibration;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final pitchPoints = _generatePitchVisualization();

    return Scaffold(
      body: Stack(
        children: [
          Positioned.fill(
            child: Pitch3DViewer(
              trajectoryPoints: pitchPoints,
              showAnimation: false,
            ),
          ),
          Positioned.fill(
            child: DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [
                    Colors.black.withValues(alpha: 0.35),
                    Colors.black.withValues(alpha: 0.15),
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
                      _Chip(text: 'Calibration success', color: const Color(0xFF4ADE80)),
                      const Spacer(),
                      IconButton(
                        onPressed: () => Navigator.of(context).pop(),
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
                        color: Colors.black.withValues(alpha: 0.25),
                        blurRadius: 22,
                        offset: const Offset(0, 16),
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
                        'Pitch corners and stumps are locked in. Deliveries on this pitch can now be analyzed with calibrated accuracy.',
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                      const SizedBox(height: 16),
                      Row(
                        children: [
                          _Stat(label: 'Pitch length', value: '20.12 m'),
                          const SizedBox(width: 12),
                          _Stat(label: 'Width', value: '3.05 m'),
                          const SizedBox(width: 12),
                          _Stat(label: 'Stump height', value: '0.71 m'),
                        ],
                      ),
                      const SizedBox(height: 22),
                      Row(
                        children: [
                          Expanded(
                            child: FilledButton.icon(
                              onPressed: () => Navigator.of(context).pop(),
                              icon: const Icon(Icons.check),
                              label: const Text('Done'),
                              style: FilledButton.styleFrom(
                                padding: const EdgeInsets.symmetric(vertical: 16),
                              ),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: OutlinedButton.icon(
                              onPressed: () => Navigator.of(context).pop(),
                              icon: const Icon(Icons.analytics_outlined),
                              label: const Text('Analyze now'),
                              style: OutlinedButton.styleFrom(
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

  /// Generate a simple 3D visualization of the calibrated pitch
  List<Map<String, double>> _generatePitchVisualization() {
    // The Three.js scene uses:
    // - x: along pitch length (batting stumps at x=0, bowling end at x=20.12)
    // - y: lateral across the pitch (we feed this as "y" and hawkeye.js maps it to Z)
    // - z: height
    const pitchLength = 20.12;
    const pitchWidth = 3.05;
    final halfW = pitchWidth / 2.0;

    return <Map<String, double>>[
      {'x': 0.0, 'y': -halfW, 'z': 0.0},
      {'x': 0.0, 'y': halfW, 'z': 0.0},
      {'x': pitchLength, 'y': halfW, 'z': 0.0},
      {'x': pitchLength, 'y': -halfW, 'z': 0.0},
      {'x': 0.0, 'y': -halfW, 'z': 0.0},
    ];
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.text, required this.color});
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.white.withValues(alpha: 0.16)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.check_circle, color: color, size: 16),
          const SizedBox(width: 8),
          Text(
            text.toUpperCase(),
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
          color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.35),
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
