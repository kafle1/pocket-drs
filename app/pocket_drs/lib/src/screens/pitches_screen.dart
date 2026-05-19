import 'package:flutter/material.dart';

import '../models/pitch.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../utils/pitch_store.dart';
import '../widgets/drs_button.dart';
import '../widgets/drs_scaffold.dart';
import '../widgets/status_chip.dart';
import 'pitch_calibration_screen.dart';
import 'pitch_detail_screen.dart';
import 'pitch_edit_screen.dart';

class PitchesScreen extends StatefulWidget {
  const PitchesScreen({super.key});

  @override
  State<PitchesScreen> createState() => _PitchesScreenState();
}

class _PitchesScreenState extends State<PitchesScreen> {
  final _store = PitchStore();

  bool _loading = true;
  String? _error;
  List<Pitch> _pitches = const <Pitch>[];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final pitches = await _store.loadAll();
      if (!mounted) return;
      setState(() {
        _pitches = pitches;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'Failed to load pitches';
        _loading = false;
      });
    }
  }

  Future<void> _deletePitch(Pitch pitch) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete pitch?'),
        content: Text('"${pitch.name}" and all of its calibration will be removed.'),
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
    if (confirmed != true || !mounted) return;
    try {
      await _store.delete(pitch.id);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Removed ${pitch.name}')),
        );
        _load();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to delete: $e')),
        );
      }
    }
  }

  Future<void> _createPitchAndCalibrate() async {
    final name = await Navigator.of(context).push<String>(
      MaterialPageRoute(builder: (_) => const PitchEditScreen()),
    );
    if (name == null || name.trim().isEmpty || !mounted) return;

    Pitch pitch;
    try {
      pitch = await _store.create(name: name);
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please sign in again')),
      );
      return;
    }
    if (!mounted) return;

    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => PitchCalibrationScreen(
          pitchId: pitch.id,
          pitchName: pitch.name,
        ),
      ),
    );
    if (mounted) _load();
  }

  @override
  Widget build(BuildContext context) {
    final calibrated = _pitches.where((p) => p.isCalibrated).length;
    return Scaffold(
      appBar: DrsHeader(
        eyebrow: 'WORKSPACE',
        title: 'Pitches',
        actions: [
          IconButton(
            tooltip: 'Refresh',
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh, size: 20),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? _ErrorState(message: _error!, onRetry: _load)
              : _pitches.isEmpty
                  ? _EmptyState(onCreate: _createPitchAndCalibrate)
                  : _List(
                      pitches: _pitches,
                      calibratedCount: calibrated,
                      onOpen: (pitch) async {
                        await Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => PitchDetailScreen(pitchId: pitch.id),
                          ),
                        );
                        _load();
                      },
                      onDelete: _deletePitch,
                      onCreate: _createPitchAndCalibrate,
                    ),
    );
  }
}

class _List extends StatelessWidget {
  const _List({
    required this.pitches,
    required this.calibratedCount,
    required this.onOpen,
    required this.onDelete,
    required this.onCreate,
  });

  final List<Pitch> pitches;
  final int calibratedCount;
  final void Function(Pitch) onOpen;
  final void Function(Pitch) onDelete;
  final VoidCallback onCreate;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListView(
      padding: EdgeInsets.zero,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.xl,
            AppSpacing.lg,
            AppSpacing.xl,
            AppSpacing.md,
          ),
          child: Row(
            children: [
              Text(
                pitches.length.toString().padLeft(2, '0'),
                style: AppTypography.mono(theme.textTheme.displayMedium),
              ),
              const SizedBox(width: AppSpacing.lg),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(
                      pitches.length == 1 ? 'PITCH IN LIBRARY' : 'PITCHES IN LIBRARY',
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      '$calibratedCount / ${pitches.length} CALIBRATED',
                      style: theme.textTheme.labelMedium,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.xl,
            0,
            AppSpacing.xl,
            AppSpacing.lg,
          ),
          child: DrsButton(
            label: 'NEW PITCH',
            icon: Icons.add,
            onPressed: onCreate,
          ),
        ),
        Container(height: 1, color: theme.colorScheme.outline),
        for (final p in pitches)
          _PitchRow(
            pitch: p,
            onTap: () => onOpen(p),
            onDelete: () => onDelete(p),
          ),
      ],
    );
  }
}

class _PitchRow extends StatelessWidget {
  const _PitchRow({required this.pitch, required this.onTap, required this.onDelete});
  final Pitch pitch;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final isDark = theme.brightness == Brightness.dark;
    final isCalibrated = pitch.isCalibrated;

    return Dismissible(
      key: ValueKey(pitch.id),
      direction: DismissDirection.endToStart,
      confirmDismiss: (_) async {
        onDelete();
        return false;
      },
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: AppSpacing.xl),
        color: AppColors.signalRed,
        child: const Icon(Icons.delete_outline, color: AppColors.bone),
      ),
      child: Material(
        color: scheme.surface,
        child: InkWell(
          onTap: onTap,
          child: Container(
            decoration: BoxDecoration(
              border: Border(
                bottom: BorderSide(color: scheme.outline, width: 1),
              ),
            ),
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.xl,
              vertical: AppSpacing.lg,
            ),
            child: Row(
              children: [
                Container(
                  width: 4,
                  height: 40,
                  color: isCalibrated
                      ? AppColors.decisionNotOut(isDark)
                      : AppColors.decisionOut(isDark),
                ),
                const SizedBox(width: AppSpacing.lg),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        pitch.name,
                        style: theme.textTheme.titleLarge,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Row(
                        children: [
                          Text(
                            _relative(pitch.updatedAt).toUpperCase(),
                            style: theme.textTheme.labelSmall?.copyWith(
                              color: scheme.onSurfaceVariant,
                            ),
                          ),
                          const SizedBox(width: AppSpacing.md),
                          Container(
                            width: 3,
                            height: 3,
                            decoration: BoxDecoration(
                              color: scheme.onSurfaceVariant,
                              shape: BoxShape.circle,
                            ),
                          ),
                          const SizedBox(width: AppSpacing.md),
                          Text(
                            isCalibrated ? 'READY' : 'CALIBRATE',
                            style: theme.textTheme.labelSmall?.copyWith(
                              color: isCalibrated
                                  ? AppColors.decisionNotOut(isDark)
                                  : AppColors.decisionOut(isDark),
                            ),
                          ),
                        ],
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

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.onCreate});
  final VoidCallback onCreate;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(
            '00',
            style: AppTypography.mono(theme.textTheme.displayLarge)?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          Text(
            'No pitches yet.',
            style: theme.textTheme.headlineMedium,
          ),
          const SizedBox(height: AppSpacing.md),
          Text(
            'Calibrate your first pitch to begin tracking deliveries and reviewing LBW decisions.',
            style: theme.textTheme.bodyLarge?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: AppSpacing.xxl),
          DrsButton(label: 'NEW PITCH', icon: Icons.add, onPressed: onCreate),
        ],
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const StatusChip(label: 'ERROR', color: AppColors.signalRed),
          const SizedBox(height: AppSpacing.lg),
          Text(message, style: theme.textTheme.headlineMedium),
          const SizedBox(height: AppSpacing.xxl),
          DrsButton(label: 'RETRY', icon: Icons.refresh, onPressed: onRetry),
        ],
      ),
    );
  }
}
