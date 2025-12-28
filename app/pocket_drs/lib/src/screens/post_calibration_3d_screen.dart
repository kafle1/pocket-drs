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
          // Full screen 3D viewer
          Positioned.fill(
            child: Pitch3DViewer(
              trajectoryPoints: pitchPoints,
              showAnimation: false,
            ),
          ),
          
          // Overlay content
          SafeArea(
            child: Column(
              children: [
                // Header
                Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                        decoration: BoxDecoration(
                          color: Colors.black.withOpacity(0.6),
                          borderRadius: BorderRadius.circular(20),
                          border: Border.all(color: Colors.white.withOpacity(0.1)),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.check_circle, color: Color(0xFF4ADE80), size: 16),
                            const SizedBox(width: 8),
                            Text(
                              'CALIBRATION SUCCESSFUL',
                              style: theme.textTheme.labelSmall?.copyWith(
                                color: Colors.white,
                                fontWeight: FontWeight.bold,
                                letterSpacing: 1,
                              ),
                            ),
                          ],
                        ),
                      ),
                      const Spacer(),
                      IconButton(
                        onPressed: () => Navigator.of(context).pop(),
                        icon: const Icon(Icons.close, color: Colors.white),
                        style: IconButton.styleFrom(
                          backgroundColor: Colors.black.withOpacity(0.4),
                        ),
                      ),
                    ],
                  ),
                ),
                
                const Spacer(),
                
                // Bottom card
                Container(
                  margin: const EdgeInsets.all(16),
                  padding: const EdgeInsets.all(24),
                  decoration: BoxDecoration(
                    color: theme.colorScheme.surface,
                    borderRadius: BorderRadius.circular(24),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withOpacity(0.2),
                        blurRadius: 20,
                        offset: const Offset(0, 10),
                      ),
                    ],
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        pitchName,
                        style: theme.textTheme.titleLarge?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'Pitch corners and stumps have been calibrated. You can now analyze deliveries on this pitch with high precision.',
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                      const SizedBox(height: 24),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton.icon(
                          onPressed: () => Navigator.of(context).pop(),
                          icon: const Icon(Icons.check),
                          label: const Text('Done'),
                          style: FilledButton.styleFrom(
                            padding: const EdgeInsets.symmetric(vertical: 16),
                          ),
                        ),
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
    // Create a pitch outline using the calibrated corner points
    // In a full implementation, this would use the actual 3D coordinates
    // For now, we show a simple pitch boundary
    return [
      {'x': -10.06, 'y': 0.0, 'z': -1.525}, // Near left corner
      {'x': -10.06, 'y': 0.0, 'z': 1.525},  // Near right corner
      {'x': 10.06, 'y': 0.0, 'z': 1.525},   // Far right corner
      {'x': 10.06, 'y': 0.0, 'z': -1.525},  // Far left corner
      {'x': -10.06, 'y': 0.0, 'z': -1.525}, // Close loop
    ];
  }
}
