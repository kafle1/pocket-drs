import 'dart:math' as math;
import 'package:flutter/material.dart';

import '../analysis/ball_track_models.dart';
import '../analysis/calibration_config.dart';
import '../analysis/lbw_assessor.dart';
import '../analysis/lbw_models.dart';
import '../analysis/trajectory_3d.dart';
import '../widgets/hawkeye_3d_view.dart';

class LbwReviewScreen extends StatefulWidget {
  const LbwReviewScreen({
    super.key,
    required this.track,
    required this.calibration,
  });

  final BallTrackResult track;
  final CalibrationConfig calibration;

  @override
  State<LbwReviewScreen> createState() => _LbwReviewScreenState();
}

class _LbwReviewScreenState extends State<LbwReviewScreen> {
  List<PitchPlaneTrackPoint> _plane = const [];
  String? _error;
  int _pitchIndex = 0;
  bool _fullToss = false;

  @override
  void initState() {
    super.initState();
    _buildPitchPlaneTrack();
  }

  void _buildPitchPlaneTrack() {
    setState(() {
      _error = null;
      _plane = const [];
    });

    final pitchCal = widget.calibration.pitchCalibration;
    if (pitchCal == null) {
      setState(() => _error = 'Pitch calibration required');
      return;
    }

    try {
      final H = pitchCal.homography(
        pitchLengthM: widget.calibration.pitchLengthM,
        pitchWidthM: widget.calibration.pitchWidthM,
      );

      final out = <PitchPlaneTrackPoint>[];
      for (final p in widget.track.points) {
        final world = H.transform(p.p);
        if (world.dx.isNaN || world.dy.isNaN || world.dx.isInfinite || world.dy.isInfinite) {
          continue;
        }
        out.add(PitchPlaneTrackPoint(
          tMs: p.t,
          imagePx: p.p,
          worldM: world,
          confidence: p.confidence,
        ));
      }

      if (out.length < 4) {
        throw StateError('Not enough points (${out.length})');
      }

      final defaultPitch = (out.length * 0.35).round().clamp(0, out.length - 2);
      setState(() {
        _plane = List.unmodifiable(out);
        _pitchIndex = defaultPitch;
      });
    } catch (e) {
      setState(() => _error = e.toString());
    }
  }

  List<TrajectoryPoint3D> _build3D(int bounceIdx, int impactIdx) {
    if (_plane.isEmpty) return [];

    final est = Trajectory3DEstimator();
    final pts = _plane.map((p) => p.worldM).toList();
    final times = _plane.map((p) => p.tMs).toList();

    final traj = est.estimate(
      points: pts,
      timesMs: times,
      bounceIndex: bounceIdx,
      impactIndex: impactIdx,
    );

    return est.extendToStumps(track: traj, impactIndex: impactIdx);
  }

  String _decisionKey(LbwDecision d) {
    switch (d) {
      case LbwDecision.out:
        return 'out';
      case LbwDecision.notOut:
        return 'not_out';
      case LbwDecision.umpiresCall:
        return 'umpires_call';
    }
  }

  @override
  Widget build(BuildContext context) {
    final impactIdx = _plane.isEmpty ? 0 : _plane.length - 1;
    final maxPitch = math.max(0, impactIdx - 1);
    final bounceIdx = _fullToss ? 0 : _pitchIndex.clamp(0, maxPitch);

    LbwAssessment? assessment;
    if (_error == null && _plane.isNotEmpty && impactIdx > bounceIdx) {
      assessment = const LbwAssessor().assess(
        points: _plane,
        pitchIndex: bounceIdx,
        impactIndex: impactIdx,
      );
    }

    final trajectory3D = _build3D(bounceIdx, impactIdx);
    final decisionKey = assessment != null ? _decisionKey(assessment.wicketDecision) : '';

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
            ? _ErrorView(error: _error!, onRetry: _buildPitchPlaneTrack)
            : _plane.isEmpty
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
                                // Decision card
                                if (assessment != null) _DecisionCard(assessment: assessment),

                                const SizedBox(height: 20),

                                // Controls
                                _ControlRow(
                                  label: 'Full toss',
                                  child: Switch.adaptive(
                                    value: _fullToss,
                                    onChanged: (v) => setState(() => _fullToss = v),
                                    activeColor: const Color(0xFF3b82f6),
                                  ),
                                ),

                                if (!_fullToss) ...[
                                  const SizedBox(height: 12),
                                  Text(
                                    'Bounce point',
                                    style: TextStyle(
                                      color: Colors.white.withValues(alpha: 0.7),
                                      fontSize: 13,
                                    ),
                                  ),
                                  SliderTheme(
                                    data: SliderTheme.of(context).copyWith(
                                      activeTrackColor: const Color(0xFF3b82f6),
                                      inactiveTrackColor: const Color(0xFF334155),
                                      thumbColor: const Color(0xFF3b82f6),
                                    ),
                                    child: Slider(
                                      min: 0,
                                      max: maxPitch.toDouble(),
                                      value: bounceIdx.toDouble(),
                                      divisions: math.max(1, maxPitch),
                                      onChanged: (v) => setState(() => _pitchIndex = v.round()),
                                    ),
                                  ),
                                ],
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
  const _ErrorView({required this.error, required this.onRetry});
  final String error;
  final VoidCallback onRetry;

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
            FilledButton(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      ),
    );
  }
}

class _DecisionCard extends StatelessWidget {
  const _DecisionCard({required this.assessment});
  final LbwAssessment assessment;

  @override
  Widget build(BuildContext context) {
    Color color;
    IconData icon;

    switch (assessment.wicketDecision) {
      case LbwDecision.out:
        color = const Color(0xFFdc2626);
        icon = Icons.close;
        break;
      case LbwDecision.umpiresCall:
        color = const Color(0xFFf59e0b);
        icon = Icons.help_outline;
        break;
      case LbwDecision.notOut:
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
                  assessment.decisionText,
                  style: TextStyle(
                    color: color,
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  _checksText(),
                  style: TextStyle(color: Colors.white.withValues(alpha: 0.6), fontSize: 12),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  String _checksText() {
    final checks = <String>[];
    if (assessment.pitchedInLine) checks.add('Pitched ✓');
    if (assessment.impactInLine) checks.add('Impact ✓');
    if (assessment.wouldHitStumps) checks.add('Hitting ✓');
    return checks.join('  ·  ');
  }
}

class _ControlRow extends StatelessWidget {
  const _ControlRow({required this.label, required this.child});
  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: const TextStyle(color: Colors.white, fontSize: 15)),
        child,
      ],
    );
  }
}
