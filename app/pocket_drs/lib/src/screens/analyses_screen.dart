import 'package:flutter/material.dart';

import '../api/analysis_result.dart';
import '../models/analysis_record.dart';
import '../services/auth_service.dart';
import '../services/firestore_service.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../widgets/decision_badge.dart';
import '../widgets/drs_scaffold.dart';
import '../widgets/status_chip.dart';
import 'analysis_detail_screen.dart';

class AnalysesScreen extends StatefulWidget {
  const AnalysesScreen({super.key, this.pitchId});

  final String? pitchId;

  @override
  State<AnalysesScreen> createState() => _AnalysesScreenState();
}

class _AnalysesScreenState extends State<AnalysesScreen> {
  late final FirestoreService _store = FirestoreService(AuthService());

  Future<void> _delete(AnalysisRecord r) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete analysis?'),
        content: const Text('The saved trajectory and decision will be removed.'),
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
    if (ok != true) return;
    try {
      await _store.deleteAnalysis(r.id);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Failed to delete')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final isPitchScoped = widget.pitchId != null;
    return Scaffold(
      appBar: isPitchScoped
          ? const DrsSubHeader(eyebrow: 'PITCH HISTORY', title: 'Past Analyses')
          : const DrsHeader(eyebrow: 'LIBRARY', title: 'Analyses'),
      body: StreamBuilder<List<AnalysisRecord>>(
        stream: _store.watchAnalyses(pitchId: widget.pitchId),
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return _Error(detail: '${snap.error}');
          }
          final records = snap.data ?? const <AnalysisRecord>[];
          if (records.isEmpty) return const _Empty();
          return _AnalysesList(records: records, onDelete: _delete);
        },
      ),
    );
  }
}

class _AnalysesList extends StatelessWidget {
  const _AnalysesList({required this.records, required this.onDelete});
  final List<AnalysisRecord> records;
  final void Function(AnalysisRecord) onDelete;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;

    final outCount = records.where((r) => r.result.lbw?.decision == LbwDecisionKey.out).length;
    final notOutCount = records.where((r) => r.result.lbw?.decision == LbwDecisionKey.notOut).length;
    final umpireCount = records.where((r) => r.result.lbw?.decision == LbwDecisionKey.umpiresCall).length;

    return ListView(
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
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                records.length.toString().padLeft(2, '0'),
                style: AppTypography.mono(theme.textTheme.displayMedium),
              ),
              const SizedBox(width: AppSpacing.lg),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        records.length == 1 ? 'DELIVERY ANALYSED' : 'DELIVERIES ANALYSED',
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: scheme.onSurfaceVariant,
                        ),
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      Row(
                        children: [
                          _Tally(label: 'OUT', count: outCount, color: AppColors.signalRed),
                          const SizedBox(width: AppSpacing.md),
                          _Tally(label: 'NOT', count: notOutCount, color: AppColors.pitchGreen),
                          const SizedBox(width: AppSpacing.md),
                          _Tally(label: 'UMP', count: umpireCount, color: AppColors.caution),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
        Container(height: 1, color: scheme.outline),
        for (final r in records)
          _AnalysisRow(
            record: r,
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => AnalysisDetailScreen(record: r)),
            ),
            onDelete: () => onDelete(r),
          ),
        const SizedBox(height: AppSpacing.xl),
      ],
    );
  }
}

class _Tally extends StatelessWidget {
  const _Tally({required this.label, required this.count, required this.color});
  final String label;
  final int count;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 6,
          height: 6,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: AppSpacing.xs + 2),
        Text(
          '$count $label',
          style: theme.textTheme.labelSmall,
        ),
      ],
    );
  }
}

class _AnalysisRow extends StatelessWidget {
  const _AnalysisRow({required this.record, required this.onTap, required this.onDelete});

  final AnalysisRecord record;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final lbw = record.result.lbw;

    return Dismissible(
      key: ValueKey(record.id),
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
              border: Border(bottom: BorderSide(color: scheme.outline, width: 1)),
            ),
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.xl,
              vertical: AppSpacing.lg,
            ),
            child: Row(
              children: [
                DecisionBadge(decision: lbw?.decision, size: DecisionBadgeSize.small),
                const SizedBox(width: AppSpacing.lg),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        lbw?.reason ?? 'No reasoning available',
                        style: theme.textTheme.titleMedium,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Text(
                        _relative(record.createdAt).toUpperCase(),
                        style: theme.textTheme.labelSmall?.copyWith(
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

class _Empty extends StatelessWidget {
  const _Empty();

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
          Text('No analyses yet.', style: theme.textTheme.headlineMedium),
          const SizedBox(height: AppSpacing.md),
          Text(
            'Run an analysis from a calibrated pitch to see the trajectory and LBW decision here.',
            style: theme.textTheme.bodyLarge?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }
}

class _Error extends StatelessWidget {
  const _Error({required this.detail});
  final String detail;

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
          Text('Failed to load analyses', style: theme.textTheme.headlineSmall),
          const SizedBox(height: AppSpacing.sm),
          Text(
            detail,
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }
}
