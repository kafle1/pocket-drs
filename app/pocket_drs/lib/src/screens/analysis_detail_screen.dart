import 'package:flutter/material.dart';

import '../analysis/pitch_pose.dart';
import '../api/analysis_result.dart';
import '../models/analysis_record.dart';
import '../utils/pitch_store.dart';
import '../widgets/pitch_3d_viewer.dart';

/// Read-only view of a saved analysis: 3D trajectory + decision + key metrics.
class AnalysisDetailScreen extends StatefulWidget {
  const AnalysisDetailScreen({super.key, required this.record});

  final AnalysisRecord record;

  @override
  State<AnalysisDetailScreen> createState() => _AnalysisDetailScreenState();
}

class _AnalysisDetailScreenState extends State<AnalysisDetailScreen> {
  PitchPose? _pose;
  String? _pitchName;

  @override
  void initState() {
    super.initState();
    _loadPose();
  }

  Future<void> _loadPose() async {
    final pid = widget.record.pitchId;
    if (pid == null) return;
    try {
      final pitch = await PitchStore().loadById(pid);
      final cal = pitch?.calibration?.pitchCalibration;
      if (!mounted) return;
      setState(() {
        _pitchName = pitch?.name;
        _pose = cal == null ? null : PitchPoseEstimator.fromCalibration(cal);
      });
    } catch (_) {/* pose is optional */}
  }

  @override
  Widget build(BuildContext context) {
    final r = widget.record.result;
    final world = r.worldTrajectory;

    final allPoints = <Map<String, double>>[
      for (final p in world.points) p.toViewerJson(),
      for (final p in world.predictedToStumps) p.toViewerJson(),
    ];

    int bounceIdx = -1;
    int impactIdx = -1;
    if (r.events?.bounce != null) {
      bounceIdx = _indexNearestT(world.points, r.events!.bounce!.tMs);
    }
    if (r.events?.impact != null) {
      impactIdx = _indexNearestT(world.points, r.events!.impact!.tMs);
    }
    if (bounceIdx < 0) bounceIdx = (allPoints.length / 2).floor();
    if (impactIdx < 0) impactIdx = world.points.length - 1;

    final decision = switch (r.lbw?.decision) {
      LbwDecisionKey.out => 'out',
      LbwDecisionKey.notOut => 'not_out',
      LbwDecisionKey.umpiresCall => 'umpires_call',
      _ => null,
    };

    return Scaffold(
      appBar: AppBar(
        title: Text(_pitchName ?? 'Analysis'),
      ),
      body: Column(
        children: [
          Expanded(
            child: allPoints.isEmpty
                ? _NoTrajectory(reason: r.lbw?.reason ?? r.warnings.firstOrNull)
                : Pitch3DViewer(
                    trajectoryPoints: allPoints,
                    bounceIndex: bounceIdx,
                    impactIndex: impactIdx,
                    decision: decision,
                    showAnimation: true,
                    pose: _pose,
                  ),
          ),
          _MetricsPanel(result: r),
        ],
      ),
    );
  }

  static int _indexNearestT(List<WorldPointM> pts, int tMs) {
    var best = -1; var bestDelta = 1 << 30;
    for (var i = 0; i < pts.length; i++) {
      final d = (pts[i].tMs - tMs).abs();
      if (d < bestDelta) { bestDelta = d; best = i; }
    }
    return best;
  }
}

class _NoTrajectory extends StatelessWidget {
  const _NoTrajectory({this.reason});
  final String? reason;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.search_off, size: 48, color: theme.colorScheme.onSurfaceVariant),
            const SizedBox(height: 12),
            Text('No trajectory recovered', style: theme.textTheme.titleMedium),
            if (reason != null) ...[
              const SizedBox(height: 6),
              Text(reason!, style: theme.textTheme.bodySmall, textAlign: TextAlign.center),
            ],
          ],
        ),
      ),
    );
  }
}

class _MetricsPanel extends StatelessWidget {
  const _MetricsPanel({required this.result});
  final AnalysisResult result;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final lbw = result.lbw;
    final fit = result.worldTrajectory.fit;
    final ev = result.events;
    final cal = result.calibrationQuality;

    final decisionLabel = switch (lbw?.decision) {
      LbwDecisionKey.out => 'OUT',
      LbwDecisionKey.notOut => 'NOT OUT',
      LbwDecisionKey.umpiresCall => "UMPIRE'S CALL",
      _ => '—',
    };
    final (badgeBg, badgeFg) = switch (lbw?.decision) {
      LbwDecisionKey.out => (theme.colorScheme.errorContainer, theme.colorScheme.onErrorContainer),
      LbwDecisionKey.notOut => (theme.colorScheme.tertiaryContainer, theme.colorScheme.onTertiaryContainer),
      LbwDecisionKey.umpiresCall => (theme.colorScheme.secondaryContainer, theme.colorScheme.onSecondaryContainer),
      _ => (theme.colorScheme.surfaceContainerHighest, theme.colorScheme.onSurfaceVariant),
    };

    return Container(
      padding: const EdgeInsets.fromLTRB(20, 18, 20, 24),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
        border: Border(top: BorderSide(color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3))),
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                  decoration: BoxDecoration(color: badgeBg, borderRadius: BorderRadius.circular(10)),
                  child: Text(
                    decisionLabel,
                    style: theme.textTheme.titleMedium?.copyWith(
                      color: badgeFg, fontWeight: FontWeight.w800, letterSpacing: 0.6,
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                if (lbw != null)
                  Expanded(
                    child: Text(
                      lbw.reason,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                      maxLines: 2, overflow: TextOverflow.ellipsis,
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 10, runSpacing: 10,
              children: [
                if (lbw?.yAtStumpsM != null)
                  _Metric(label: 'Stumps Y', value: '${(lbw!.yAtStumpsM! * 100).toStringAsFixed(1)} cm'),
                if (lbw?.zAtStumpsM != null)
                  _Metric(label: 'Stumps Z', value: '${(lbw!.zAtStumpsM! * 100).toStringAsFixed(0)} cm'),
                if (ev?.bounce != null)
                  _Metric(label: 'Bounce X', value: '${ev!.bounce!.xM.toStringAsFixed(2)} m'),
                if (fit != null)
                  _Metric(label: 'Speed', value: '${(fit.vx.abs() * 3.6).toStringAsFixed(0)} km/h'),
                if (fit != null)
                  _Metric(label: 'Fit RMS', value: '${(fit.rmsM * 100).toStringAsFixed(0)} cm'),
                if (cal.reprojErrorPx != null)
                  _Metric(label: 'Cal err', value: '${cal.reprojErrorPx!.toStringAsFixed(1)} px'),
                if (lbw != null)
                  _Metric(label: 'Confidence', value: '${(lbw.confidence * 100).round()} %'),
              ],
            ),
            if (result.warnings.isNotEmpty) ...[
              const SizedBox(height: 14),
              ...result.warnings.map(
                (w) => Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(Icons.info_outline, size: 16, color: theme.colorScheme.onSurfaceVariant),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          w,
                          style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label, style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
          const SizedBox(width: 8),
          Text(value, style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}
