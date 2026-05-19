import 'package:flutter/material.dart';

import '../analysis/pitch_pose.dart';
import '../models/pitch.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../utils/pitch_store.dart';
import '../widgets/drs_button.dart';
import '../widgets/drs_scaffold.dart';
import '../widgets/pitch_3d_viewer.dart';
import '../widgets/section_label.dart';
import '../widgets/status_chip.dart';
import 'analyses_screen.dart';
import 'delivery_processing_screen.dart';
import 'pitch_calibration_screen.dart';
import 'pitch_edit_screen.dart';

class PitchDetailScreen extends StatefulWidget {
  const PitchDetailScreen({super.key, required this.pitchId});
  final String pitchId;

  @override
  State<PitchDetailScreen> createState() => _PitchDetailScreenState();
}

class _PitchDetailScreenState extends State<PitchDetailScreen> {
  final _store = PitchStore();
  bool _loading = true;
  String? _error;
  Pitch? _pitch;

  PitchPose? get _pitchPose {
    final cal = _pitch?.calibration?.pitchCalibration;
    if (cal == null) return null;
    return PitchPoseEstimator.fromCalibration(cal);
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final pitch = await _store.loadById(widget.pitchId);
      if (mounted) {
        setState(() {
          _pitch = pitch;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
          _loading = false;
        });
      }
    }
  }

  Future<void> _edit() async {
    final pitch = _pitch;
    if (pitch == null) return;
    final name = await Navigator.of(context).push<String?>(
      MaterialPageRoute(builder: (_) => PitchEditScreen(initial: pitch)),
    );
    if (name == null || !mounted) return;
    try {
      await _store.update(pitch.copyWith(name: name, updatedAt: DateTime.now()));
      _load();
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please sign in again')),
      );
    }
  }

  Future<void> _delete() async {
    final pitch = _pitch;
    if (pitch == null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete pitch?'),
        content: Text('"${pitch.name}" will be removed permanently.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('CANCEL')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
              foregroundColor: Theme.of(context).colorScheme.onError,
            ),
            child: const Text('DELETE'),
          ),
        ],
      ),
    );
    if (ok == true && mounted) {
      try {
        await _store.delete(pitch.id);
        if (mounted) Navigator.pop(context);
      } catch (_) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Please sign in again')),
        );
      }
    }
  }

  Future<void> _calibrate() async {
    final pitch = _pitch;
    if (pitch == null) return;
    final done = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => PitchCalibrationScreen(pitchId: pitch.id, pitchName: pitch.name),
      ),
    );
    if (done == true && mounted) _load();
  }

  Future<void> _analyze() async {
    final pitch = _pitch;
    if (pitch == null || !pitch.isCalibrated) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Calibrate the pitch first')),
      );
      return;
    }
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => DeliveryProcessingScreen(pitchId: pitch.id, pitchName: pitch.name),
      ),
    );
  }

  void _view3DFullscreen() {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => _Fullscreen3DViewer(pose: _pitchPose)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final pitch = _pitch;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final calibrated = pitch?.isCalibrated ?? false;
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;

    return Scaffold(
      appBar: DrsSubHeader(
        eyebrow: 'PITCH',
        title: pitch?.name ?? 'Loading',
        actions: [
          IconButton(
            icon: const Icon(Icons.edit_outlined, size: 20),
            onPressed: _edit,
            tooltip: 'Edit',
          ),
          IconButton(
            icon: const Icon(Icons.delete_outline, size: 20),
            onPressed: _delete,
            tooltip: 'Delete',
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? _ErrorView(error: _error!, onRetry: _load)
              : pitch == null
                  ? const Center(child: Text('Pitch not found'))
                  : ListView(
                      padding: EdgeInsets.zero,
                      children: [
                        Padding(
                          padding: const EdgeInsets.fromLTRB(
                            AppSpacing.xl,
                            AppSpacing.lg,
                            AppSpacing.xl,
                            AppSpacing.lg,
                          ),
                          child: Row(
                            children: [
                              StatusChip(
                                label: calibrated ? 'CALIBRATED' : 'NEEDS CALIBRATION',
                                color: calibrated
                                    ? AppColors.decisionNotOut(isDark)
                                    : AppColors.decisionOut(isDark),
                              ),
                              const SizedBox(width: AppSpacing.sm),
                              Text(
                                _relative(pitch.updatedAt).toUpperCase(),
                                style: theme.textTheme.labelSmall?.copyWith(
                                  color: scheme.onSurfaceVariant,
                                ),
                              ),
                            ],
                          ),
                        ),
                        if (calibrated) ...[
                          _ViewerCard(
                            onView3D: _view3DFullscreen,
                            pose: _pitchPose,
                          ),
                          const SizedBox(height: AppSpacing.xxl),
                        ] else ...[
                          Container(
                            height: 1,
                            color: scheme.outline,
                          ),
                          Padding(
                            padding: const EdgeInsets.fromLTRB(
                              AppSpacing.xl,
                              AppSpacing.xl,
                              AppSpacing.xl,
                              AppSpacing.xxl,
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  '01.',
                                  style: AppTypography.mono(theme.textTheme.displayMedium)?.copyWith(
                                    color: AppColors.signalRed,
                                  ),
                                ),
                                const SizedBox(height: AppSpacing.md),
                                Text('Calibrate this pitch.', style: theme.textTheme.headlineSmall),
                                const SizedBox(height: AppSpacing.sm),
                                Text(
                                  'Mark four pitch corners and both sets of stumps so the server can recover 3D ball trajectories.',
                                  style: theme.textTheme.bodyMedium?.copyWith(
                                    color: scheme.onSurfaceVariant,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xl),
                          child: const SectionLabel(label: 'ACTIONS'),
                        ),
                        if (calibrated) ...[
                          _ActionRow(
                            number: '01',
                            title: 'Analyse delivery',
                            subtitle: 'Upload or record a ball video',
                            onTap: _analyze,
                            accent: true,
                          ),
                          _ActionRow(
                            number: '02',
                            title: 'Past analyses',
                            subtitle: 'Trajectories and decisions on this pitch',
                            onTap: () => Navigator.of(context).push(
                              MaterialPageRoute(
                                builder: (_) => AnalysesScreen(pitchId: pitch.id),
                              ),
                            ),
                          ),
                          _ActionRow(
                            number: '03',
                            title: 'Re-calibrate',
                            subtitle: 'Remap pitch corners and stumps',
                            onTap: _calibrate,
                          ),
                        ] else
                          _ActionRow(
                            number: '01',
                            title: 'Calibrate pitch',
                            subtitle: 'Mark corners and stumps for 3D tracking',
                            onTap: _calibrate,
                            accent: true,
                          ),
                        const SizedBox(height: AppSpacing.xxl),
                      ],
                    ),
    );
  }

  static String _relative(DateTime t) {
    final d = DateTime.now().difference(t);
    if (d.inMinutes < 1) return 'just now';
    if (d.inMinutes < 60) return '${d.inMinutes}m ago';
    if (d.inHours < 24) return '${d.inHours}h ago';
    if (d.inDays < 7) return '${d.inDays}d ago';
    return '${t.day}/${t.month}/${t.year}';
  }
}

class _ViewerCard extends StatelessWidget {
  const _ViewerCard({required this.onView3D, this.pose});
  final VoidCallback onView3D;
  final PitchPose? pose;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return GestureDetector(
      onTap: onView3D,
      child: Container(
        height: 320,
        margin: EdgeInsets.zero,
        decoration: BoxDecoration(
          color: scheme.surfaceContainer,
          border: Border(
            top: BorderSide(color: scheme.outline, width: 1),
            bottom: BorderSide(color: scheme.outline, width: 1),
          ),
        ),
        child: Stack(
          children: [
            Positioned.fill(child: Pitch3DViewer(pose: pose)),
            Positioned(
              left: AppSpacing.lg,
              top: AppSpacing.lg,
              child: Row(
                children: [
                  Text(
                    'PITCH-3D',
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: AppColors.bone,
                    ),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Container(
                    width: 4,
                    height: 4,
                    decoration: const BoxDecoration(
                      color: AppColors.signalRed,
                      shape: BoxShape.circle,
                    ),
                  ),
                ],
              ),
            ),
            Positioned(
              right: AppSpacing.lg,
              bottom: AppSpacing.lg,
              child: Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.md,
                  vertical: AppSpacing.sm,
                ),
                decoration: BoxDecoration(
                  color: AppColors.inkBlack.withValues(alpha: 0.7),
                  border: Border.all(color: AppColors.bone.withValues(alpha: 0.2), width: 1),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.open_in_full, size: 12, color: AppColors.bone),
                    const SizedBox(width: AppSpacing.sm),
                    Text(
                      'FULLSCREEN',
                      style: theme.textTheme.labelSmall?.copyWith(color: AppColors.bone),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ActionRow extends StatelessWidget {
  const _ActionRow({
    required this.number,
    required this.title,
    required this.subtitle,
    required this.onTap,
    this.accent = false,
  });

  final String number;
  final String title;
  final String subtitle;
  final VoidCallback onTap;
  final bool accent;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return Material(
      color: scheme.surface,
      child: InkWell(
        onTap: onTap,
        child: Container(
          decoration: BoxDecoration(
            border: Border(bottom: BorderSide(color: scheme.outline, width: 1)),
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.xl,
            vertical: AppSpacing.lg,
          ),
          child: Row(
            children: [
              SizedBox(
                width: 48,
                child: Text(
                  number,
                  style: AppTypography.mono(theme.textTheme.headlineMedium)?.copyWith(
                    color: accent ? AppColors.signalRed : scheme.onSurfaceVariant,
                  ),
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: theme.textTheme.titleLarge),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      subtitle,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: scheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Icon(Icons.arrow_forward, size: 18, color: scheme.onSurfaceVariant),
            ],
          ),
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
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.all(AppSpacing.xl),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const StatusChip(label: 'ERROR', color: AppColors.signalRed),
          const SizedBox(height: AppSpacing.lg),
          Text(error, style: theme.textTheme.headlineSmall),
          const SizedBox(height: AppSpacing.xxl),
          DrsButton(label: 'RETRY', icon: Icons.refresh, onPressed: onRetry),
        ],
      ),
    );
  }
}

class _Fullscreen3DViewer extends StatelessWidget {
  const _Fullscreen3DViewer({this.pose});
  final PitchPose? pose;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.inkBlack,
      body: Stack(
        children: [
          Positioned.fill(child: Pitch3DViewer(pose: pose)),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.md,
                      vertical: AppSpacing.sm,
                    ),
                    decoration: BoxDecoration(
                      color: AppColors.inkBlack.withValues(alpha: 0.7),
                      border: Border.all(color: AppColors.bone.withValues(alpha: 0.2)),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
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
                          'PITCH-3D / FULLSCREEN',
                          style: Theme.of(context).textTheme.labelSmall?.copyWith(
                                color: AppColors.bone,
                              ),
                        ),
                      ],
                    ),
                  ),
                  const Spacer(),
                  Material(
                    color: AppColors.inkBlack.withValues(alpha: 0.7),
                    shape: const RoundedRectangleBorder(
                      borderRadius: BorderRadius.all(Radius.circular(AppRadius.sm)),
                      side: BorderSide(color: Color(0x33FFFFFF), width: 1),
                    ),
                    child: IconButton(
                      onPressed: () => Navigator.of(context).pop(),
                      icon: const Icon(Icons.close, color: AppColors.bone, size: 18),
                    ),
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
