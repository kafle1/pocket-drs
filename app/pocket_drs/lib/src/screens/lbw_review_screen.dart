import 'package:flutter/material.dart';

import '../analysis/calibration_config.dart';
import '../analysis/trajectory_3d.dart';
import '../api/analysis_result.dart';
import '../widgets/hawkeye_3d_view.dart';

class LbwReviewScreen extends StatefulWidget {
  const LbwReviewScreen({
    super.key,
    required this.analysis,
    required this.calibration,
  });

  final AnalysisResult analysis;
  final CalibrationConfig calibration;

  @override
  State<LbwReviewScreen> createState() => _LbwReviewScreenState();
}

class _LbwReviewScreenState extends State<LbwReviewScreen> {
  String? _error;
  late final int _bounceIndex;
  late final int _impactIndex;

  @override
  void initState() {
    super.initState();

    final events = widget.analysis.events;
    final n = widget.analysis.pitchPlane.length;
    if (events == null || n == 0) {
      _error = 'LBW data missing. Re-run analysis with pitch calibration (4 corner taps).';
      _bounceIndex = 0;
      _impactIndex = 0;
      return;
    }

    _bounceIndex = events.bounceIndex.clamp(0, n - 1);
    _impactIndex = events.impactIndex.clamp(0, n - 1);
    if (_impactIndex <= _bounceIndex) {
      _error = 'Invalid event indices returned by server (bounce >= impact).';
    }
  }

  List<TrajectoryPoint3D> _build3D(int bounceIdx, int impactIdx) {
    final plane = widget.analysis.pitchPlane;
    if (plane.isEmpty) return [];

    final est = Trajectory3DEstimator();
    final pts = plane.map((p) => p.worldM).toList();
    final times = plane.map((p) => p.tMs).toList();

    final traj = est.estimate(
      points: pts,
      timesMs: times,
      bounceIndex: bounceIdx,
      impactIndex: impactIdx,
    );

    return est.extendToStumps(track: traj, impactIndex: impactIdx);
  }

  String _decisionKey(LbwDecisionKey d) => switch (d) {
        LbwDecisionKey.out => 'out',
        LbwDecisionKey.notOut => 'not_out',
        LbwDecisionKey.umpiresCall => 'umpires_call',
      };

  @override
  Widget build(BuildContext context) {
    final lbw = widget.analysis.lbw;
    if (lbw == null) {
      return Scaffold(
        backgroundColor: const Color(0xFF0f172a),
        appBar: AppBar(
          backgroundColor: Colors.transparent,
          elevation: 0,
          title: const Text('Decision Review', style: TextStyle(fontWeight: FontWeight.w600)),
          centerTitle: true,
        ),
        body: const SafeArea(
          child: Center(
            child: Padding(
              padding: EdgeInsets.all(24),
              child: Text(
                'No LBW decision available for this clip.\n\nRe-run analysis with pitch calibration (4 corner taps).',
                textAlign: TextAlign.center,
                style: TextStyle(color: Colors.white70),
              ),
            ),
          ),
        ),
      );
    }

    final bounceIdx = _bounceIndex;
    final impactIdx = _impactIndex;
    final trajectory3D = _build3D(bounceIdx, impactIdx);
    final decisionKey = _decisionKey(lbw.decision);

    return Scaffold(
      backgroundColor: const Color(0xFF0f172a),
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: const Text('Decision Review', style: TextStyle(fontWeight: FontWeight.w600)),
        centerTitle: true,
      ),
      body: SafeArea(
        child: _error != null
            ? _ErrorView(error: _error!)
            : widget.analysis.pitchPlane.isEmpty
                ? const Center(child: CircularProgressIndicator(strokeWidth: 2))
                : Column(
                    children: [
                      // 3D View
                      Expanded(
                        flex: 3,
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Hawkeye3DView(
                            trajectory: trajectory3D,
                            bounceIndex: bounceIdx,
                            impactIndex: impactIdx,
                            decision: decisionKey,
                          ),
                        ),
                      ),

                      // Controls
                      Expanded(
                        flex: 2,
                        child: Container(
                          decoration: BoxDecoration(
                            color: const Color(0xFF1e293b),
                            borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
                          ),
                          child: SingleChildScrollView(
                            padding: const EdgeInsets.all(20),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                _DecisionCard(lbw: lbw),

                                const SizedBox(height: 16),
                                Text(
                                  'Bounce index: $bounceIdx · Impact index: $impactIdx',
                                  style: TextStyle(color: Colors.white.withValues(alpha: 0.6), fontSize: 12),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.error});
  final String error;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 48, color: Colors.red.shade400),
            const SizedBox(height: 16),
            Text(
              error,
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.white70),
            ),
            const SizedBox(height: 24),
            const Text(
              'Go back and re-run analysis.',
              style: TextStyle(color: Colors.white54),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}

class _DecisionCard extends StatelessWidget {
  const _DecisionCard({required this.lbw});
  final LbwResult lbw;

  @override
  Widget build(BuildContext context) {
    Color color;
    IconData icon;

    switch (lbw.decision) {
      case LbwDecisionKey.out:
        color = const Color(0xFFdc2626);
        icon = Icons.close;
        break;
      case LbwDecisionKey.umpiresCall:
        color = const Color(0xFFf59e0b);
        icon = Icons.help_outline;
        break;
      case LbwDecisionKey.notOut:
        color = const Color(0xFF16a34a);
        icon = Icons.check;
        break;
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.2),
              shape: BoxShape.circle,
            ),
            child: Icon(icon, color: color, size: 24),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _decisionText(lbw.decision),
                  style: TextStyle(
                    color: color,
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  _subtitleText(),
                  style: TextStyle(color: Colors.white.withValues(alpha: 0.6), fontSize: 12),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  String _decisionText(LbwDecisionKey d) => switch (d) {
        LbwDecisionKey.out => 'OUT',
        LbwDecisionKey.notOut => 'NOT OUT',
        LbwDecisionKey.umpiresCall => 'UMPIRE\'S CALL',
      };

  String _subtitleText() {
    final checks = <String>[];
    if (lbw.pitchedInLine) checks.add('Pitched ✓');
    if (lbw.impactInLine) checks.add('Impact ✓');
    if (lbw.wicketsHitting) checks.add('Hitting ✓');
    final s = checks.join('  ·  ');
    return lbw.reason.isEmpty ? s : '$s\n${lbw.reason}';
  }
}
