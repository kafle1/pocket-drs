import 'package:flutter/material.dart';

import '../analysis/pitch_pose.dart';
import '../api/analysis_result.dart';
import '../models/analysis_record.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../utils/pitch_store.dart';
import '../widgets/decision_badge.dart';
import '../widgets/pitch_3d_viewer.dart';

/// Read-only saved analysis: 3D trajectory + decision + key metrics.
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
      backgroundColor: AppColors.inkBlack,
      body: SafeArea(
        child: Column(
          children: [
            _TopBar(name: _pitchName ?? 'Analysis'),
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
      ),
    );
  }

  static int _indexNearestT(List<WorldPointM> pts, int tMs) {
    var best = -1;
    var bestDelta = 1 << 30;
    for (var i = 0; i < pts.length; i++) {
      final d = (pts[i].tMs - tMs).abs();
      if (d < bestDelta) {
        bestDelta = d;
        best = i;
      }
    }
    return best;
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.name});
  final String name;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: AppColors.hairlineDark, width: 1)),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.sm,
          AppSpacing.xs,
          AppSpacing.lg,
          AppSpacing.sm,
        ),
        child: Row(
          children: [
            IconButton(
              onPressed: () => Navigator.of(context).maybePop(),
              icon: const Icon(Icons.arrow_back, color: AppColors.bone, size: 20),
            ),
            const SizedBox(width: AppSpacing.xs),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'REPLAY',
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: AppColors.ash,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  name.toUpperCase(),
                  style: theme.textTheme.titleMedium?.copyWith(
                    color: AppColors.bone,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.6,
                  ),
                ),
              ],
            ),
            const Spacer(),
            Container(
              width: 6,
              height: 6,
              decoration: const BoxDecoration(
                color: AppColors.signalRed,
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: AppSpacing.sm),
            Text(
              'PITCH-3D',
              style: theme.textTheme.labelSmall?.copyWith(color: AppColors.bone),
            ),
          ],
        ),
      ),
    );
  }
}

class _NoTrajectory extends StatelessWidget {
  const _NoTrajectory({this.reason});
  final String? reason;
  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.inkBlack,
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xxl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              const Icon(Icons.search_off, size: 32, color: AppColors.ash),
              const SizedBox(height: AppSpacing.lg),
              Text(
                'NO TRAJECTORY RECOVERED',
                style: TextStyle(
                  color: AppColors.bone,
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.6,
                ),
              ),
              if (reason != null) ...[
                const SizedBox(height: AppSpacing.md),
                Text(
                  reason!,
                  style: const TextStyle(color: AppColors.ash, fontSize: 13, height: 1.5),
                  textAlign: TextAlign.center,
                ),
              ],
            ],
          ),
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

    final metrics = <(String, String, String?)>[
      if (lbw?.yAtStumpsM != null)
        ('STUMPS Y', (lbw!.yAtStumpsM! * 100).toStringAsFixed(1), 'CM'),
      if (lbw?.zAtStumpsM != null)
        ('STUMPS Z', (lbw!.zAtStumpsM! * 100).toStringAsFixed(0), 'CM'),
      if (ev?.bounce != null)
        ('BOUNCE X', ev!.bounce!.xM.toStringAsFixed(2), 'M'),
      if (fit != null)
        ('SPEED', (fit.vx.abs() * 3.6).toStringAsFixed(0), 'KM/H'),
      if (fit != null)
        ('FIT RMS', (fit.rmsM * 100).toStringAsFixed(0), 'CM'),
      if (cal.reprojErrorPx != null)
        ('CAL ERR', cal.reprojErrorPx!.toStringAsFixed(1), 'PX'),
      if (lbw != null)
        ('CONF', (lbw.confidence * 100).round().toString(), '%'),
    ];

    return Container(
      decoration: const BoxDecoration(
        color: AppColors.carbon,
        border: Border(top: BorderSide(color: AppColors.hairlineDark, width: 1)),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.xl,
            AppSpacing.lg,
            AppSpacing.xl,
            AppSpacing.lg,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  DecisionBadge(decision: lbw?.decision, size: DecisionBadgeSize.large),
                  const SizedBox(width: AppSpacing.lg),
                  if (lbw != null)
                    Expanded(
                      child: Text(
                        lbw.reason,
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: AppColors.ash,
                        ),
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                ],
              ),
              if (metrics.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.lg),
                Container(height: 1, color: AppColors.hairlineDark),
                const SizedBox(height: AppSpacing.lg),
                Wrap(
                  spacing: AppSpacing.xl,
                  runSpacing: AppSpacing.md,
                  children: [
                    for (final (label, val, unit) in metrics)
                      _MetricBlock(label: label, value: val, unit: unit),
                  ],
                ),
              ],
              if (result.warnings.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.lg),
                Container(height: 1, color: AppColors.hairlineDark),
                const SizedBox(height: AppSpacing.md),
                ...result.warnings.map(
                  (w) => Padding(
                    padding: const EdgeInsets.only(top: AppSpacing.xs),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(Icons.info_outline, size: 12, color: AppColors.ash),
                        const SizedBox(width: AppSpacing.sm),
                        Expanded(
                          child: Text(
                            w,
                            style: theme.textTheme.bodySmall?.copyWith(color: AppColors.ash),
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
      ),
    );
  }
}

class _MetricBlock extends StatelessWidget {
  const _MetricBlock({required this.label, required this.value, this.unit});
  final String label;
  final String value;
  final String? unit;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: theme.textTheme.labelSmall?.copyWith(color: AppColors.ash),
        ),
        const SizedBox(height: 2),
        Row(
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            Text(
              value,
              style: AppTypography.mono(theme.textTheme.titleLarge)?.copyWith(
                color: AppColors.bone,
                fontWeight: FontWeight.w800,
              ),
            ),
            if (unit != null) ...[
              const SizedBox(width: 3),
              Text(
                unit!,
                style: theme.textTheme.labelSmall?.copyWith(color: AppColors.ash),
              ),
            ],
          ],
        ),
      ],
    );
  }
}
