import 'package:flutter/material.dart';
import '../analysis/pitch_calibration.dart';
import '../theme/app_spacing.dart';
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
    // Generate simple pitch boundary visualization using the calibration points
    final pitchPoints = _generatePitchVisualization();

    return Scaffold(
      appBar: AppBar(
        title: Text('$pitchName - Calibration Complete'),
        automaticallyImplyLeading: false,
        actions: [
          IconButton(
            icon: const Icon(Icons.check),
            onPressed: () => Navigator.of(context).pop(),
            tooltip: 'Done',
          ),
        ],
      ),
      body: Column(
        children: [
          Container(
            padding: const EdgeInsets.all(AppSpacing.md),
            color: Colors.green.shade100,
            child: Row(
              children: [
                const Icon(Icons.check_circle, color: Colors.green),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Calibration Successful',
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 16,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'Pitch corners and stumps calibrated. You can now analyze deliveries.',
                        style: TextStyle(
                          fontSize: 14,
                          color: Colors.grey.shade700,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: Pitch3DViewer(
              trajectoryPoints: pitchPoints,
              showAnimation: false,
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                onPressed: () => Navigator.of(context).pop(),
                icon: const Icon(Icons.check),
                label: const Text('Done'),
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.all(AppSpacing.md),
                ),
              ),
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
      {'x': -10.06, 'y': 0.0, 'z': -1.525}, // Back to start
    ];
  }
}
