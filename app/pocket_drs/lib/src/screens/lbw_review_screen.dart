import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../analysis/ball_track_models.dart';
import '../analysis/calibration_config.dart';
import '../analysis/lbw_assessor.dart';
import '../analysis/lbw_models.dart';

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
      setState(() {
        _error = 'Pitch calibration is missing. Go back and tap the 4 pitch corners first.';
      });
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
        out.add(
          PitchPlaneTrackPoint(
            tMs: p.t,
            imagePx: p.p,
            worldM: world,
            confidence: p.confidence,
          ),
        );
      }

      if (out.length < 4) {
        throw StateError('Not enough valid mapped points (${out.length}). Recalibrate pitch corners and try again.');
      }

      // Default pitch index around first third (common bounce location).
      final defaultPitch = (out.length * 0.35).round().clamp(0, out.length - 2);

      setState(() {
        _plane = List<PitchPlaneTrackPoint>.unmodifiable(out);
        _pitchIndex = defaultPitch;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    final plane = _plane;
    final impactIndex = plane.isEmpty ? 0 : (plane.length - 1);
    final maxPitchIndex = math.max(0, impactIndex - 1);
    final pitchIndex = _fullToss ? 0 : _pitchIndex.clamp(0, maxPitchIndex).toInt();

    LbwAssessment? assessment;
    if (_error == null && plane.isNotEmpty && impactIndex > pitchIndex) {
      assessment = const LbwAssessor().assess(
        points: plane,
        pitchIndex: pitchIndex,
        impactIndex: impactIndex,
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('LBW assist (prototype)'),
        actions: [
          IconButton(
            tooltip: 'Rebuild from calibration',
            onPressed: _buildPitchPlaneTrack,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        child: _error != null
            ? Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text('LBW analysis error', style: theme.textTheme.titleLarge),
                    const SizedBox(height: 8),
                    Text(_error!),
                    const SizedBox(height: 16),
                    FilledButton(
                      onPressed: _buildPitchPlaneTrack,
                      child: const Text('Try again'),
                    ),
                  ],
                ),
              )
            : plane.isEmpty
                ? const Center(child: CircularProgressIndicator())
                : Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(
                          child: DecoratedBox(
                            decoration: BoxDecoration(
                              color: theme.colorScheme.surfaceContainer,
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: CustomPaint(
                              painter: _TopDownPainter(
                                points: plane,
                                pitchLengthM: widget.calibration.pitchLengthM,
                                pitchWidthM: widget.calibration.pitchWidthM,
                                pitchIndex: pitchIndex,
                                impactIndex: impactIndex,
                                predictedAtStumps: assessment?.predictedAtStumps,
                              ),
                              child: const SizedBox.expand(),
                            ),
                          ),
                        ),
                        const SizedBox(height: 12),
                        SwitchListTile.adaptive(
                          contentPadding: EdgeInsets.zero,
                          title: const Text('Full toss (no bounce)'),
                          subtitle: const Text('If the ball didn\'t pitch, use release as the "pitch" point.'),
                          value: _fullToss,
                          onChanged: (v) => setState(() => _fullToss = v),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          _fullToss
                              ? 'Pitch point = first tracked point'
                              : 'Select pitch/bounce point (approx.)',
                          style: theme.textTheme.titleMedium,
                        ),
                        const SizedBox(height: 8),
                        if (!_fullToss)
                          Slider(
                            min: 0,
                            max: math.max(0, impactIndex - 1).toDouble(),
                            value: pitchIndex.toDouble(),
                            divisions: math.max(1, impactIndex - 1),
                            label: 'Index $pitchIndex',
                            onChanged: (v) => setState(() => _pitchIndex = v.round()),
                          ),
                        const SizedBox(height: 8),
                        _SummaryCard(
                          assessment: assessment,
                          pitchLengthM: widget.calibration.pitchLengthM,
                          pitchWidthM: widget.calibration.pitchWidthM,
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'Note: this is a pitch-plane approximation using homography. It does not estimate ball height or full 3D physics yet.',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ],
                    ),
                  ),
      ),
    );
  }
}

class _SummaryCard extends StatelessWidget {
  const _SummaryCard({
    required this.assessment,
    required this.pitchLengthM,
    required this.pitchWidthM,
  });

  final LbwAssessment? assessment;
  final double pitchLengthM;
  final double pitchWidthM;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final a = assessment;

    if (a == null) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Text(
            'Not enough data to assess. Try re-running tracking and pitch calibration.',
            style: theme.textTheme.bodyMedium,
          ),
        ),
      );
    }

    String yesNo(bool v) => v ? 'YES' : 'NO';

    String fmt(Offset p) => 'x=${p.dx.toStringAsFixed(2)}m, y=${p.dy.toStringAsFixed(2)}m';

    Color decisionColor;
    switch (a.wicketDecision) {
      case LbwDecision.out:
        decisionColor = Colors.red.shade700;
        break;
      case LbwDecision.umpiresCall:
        decisionColor = Colors.orange.shade700;
        break;
      case LbwDecision.notOut:
        decisionColor = Colors.green.shade700;
        break;
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: decisionColor.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                a.decisionText,
                style: theme.textTheme.titleMedium?.copyWith(
                  color: decisionColor,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
            const SizedBox(height: 12),
            Text('Pitch point: ${fmt(a.pitchPoint)}'),
            Text('Impact point: ${fmt(a.impactPoint)}'),
            Text('Predicted at stumps (x=0): y=${a.predictedAtStumps.dy.toStringAsFixed(2)}m'),
            const SizedBox(height: 8),
            Text('Pitched in line: ${yesNo(a.pitchedInLine)}'),
            Text('Impact in line: ${yesNo(a.impactInLine)}'),
            Text('Would hit stumps: ${yesNo(a.wouldHitStumps)}'),
            const SizedBox(height: 8),
            Text(
              'Wicket: ${(LbwConstants.wicketWidthM * 100).toStringAsFixed(1)}cm · Ball radius: ${(LbwConstants.ballRadiusM * 100).toStringAsFixed(1)}cm',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _TopDownPainter extends CustomPainter {
  _TopDownPainter({
    required this.points,
    required this.pitchLengthM,
    required this.pitchWidthM,
    required this.pitchIndex,
    required this.impactIndex,
    required this.predictedAtStumps,
  });

  final List<PitchPlaneTrackPoint> points;
  final double pitchLengthM;
  final double pitchWidthM;
  final int pitchIndex;
  final int impactIndex;
  final Offset? predictedAtStumps;

  @override
  void paint(Canvas canvas, Size size) {
    // World bounds to display.
    final halfW = pitchWidthM / 2.0;

    // Add margins so markers aren't flush to the border.
    const pad = 18.0;

    Rect world = Rect.fromLTRB(
      -0.8, // a bit behind stumps
      -halfW - 0.5,
      pitchLengthM + 0.8,
      halfW + 0.5,
    );

    final sx = (size.width - pad * 2) / world.width;
    final sy = (size.height - pad * 2) / world.height;
    final scale = math.min(sx, sy);

    Offset map(Offset w) {
      final x = pad + (w.dx - world.left) * scale;
      final y = pad + (w.dy - world.top) * scale;
      return Offset(x, y);
    }

    // Background.
    canvas.drawRect(
      Offset.zero & size,
      Paint()..color = const Color(0xFF0B1220).withValues(alpha: 0.03),
    );

    // Pitch rectangle (0..L, -W/2..W/2).
    final pitchRectWorld = Rect.fromLTRB(0, -halfW, pitchLengthM, halfW);
    final pitchRect = Rect.fromPoints(map(pitchRectWorld.topLeft), map(pitchRectWorld.bottomRight));

    final pitchFill = Paint()..color = const Color(0xFF16A34A).withValues(alpha: 0.10);
    final pitchStroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..color = const Color(0xFF16A34A).withValues(alpha: 0.45);

    canvas.drawRect(pitchRect, pitchFill);
    canvas.drawRect(pitchRect, pitchStroke);

    // Stumps line at x=0.
    final stumpLine = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..color = const Color(0xFF0F172A).withValues(alpha: 0.55);

    canvas.drawLine(map(Offset(0, -halfW)), map(Offset(0, halfW)), stumpLine);

    // Wicket width band.
    final tol = LbwConstants.wicketHalfWidthM;
    final wicketBand = Rect.fromLTRB(0, -tol, 0.20, tol);
    final wicketRect = Rect.fromPoints(map(wicketBand.topLeft), map(wicketBand.bottomRight));
    canvas.drawRect(
      wicketRect,
      Paint()..color = const Color(0xFFF59E0B).withValues(alpha: 0.12),
    );

    // Trajectory path.
    final path = Path();
    for (var i = 0; i < points.length; i++) {
      final p = map(points[i].worldM);
      if (i == 0) {
        path.moveTo(p.dx, p.dy);
      } else {
        path.lineTo(p.dx, p.dy);
      }
    }
    canvas.drawPath(
      path,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3
        ..color = const Color(0xFF2563EB),
    );

    // Markers.
    void dot(Offset w, Color c, {double r = 6}) {
      canvas.drawCircle(map(w), r, Paint()..color = c);
    }

    dot(points[pitchIndex].worldM, const Color(0xFFEF4444), r: 7);
    dot(points[impactIndex].worldM, const Color(0xFF7C3AED), r: 7);

    if (predictedAtStumps != null) {
      dot(predictedAtStumps!, const Color(0xFFF59E0B), r: 7);
    }
  }

  @override
  bool shouldRepaint(covariant _TopDownPainter oldDelegate) {
    return oldDelegate.points.length != points.length ||
        oldDelegate.pitchIndex != pitchIndex ||
        oldDelegate.impactIndex != impactIndex ||
        oldDelegate.predictedAtStumps != predictedAtStumps ||
        oldDelegate.pitchLengthM != pitchLengthM ||
        oldDelegate.pitchWidthM != pitchWidthM;
  }
}
