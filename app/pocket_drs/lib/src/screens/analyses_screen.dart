import 'package:flutter/material.dart';

import '../api/analysis_result.dart';
import '../models/analysis_record.dart';
import '../services/auth_service.dart';
import '../services/firestore_service.dart';
import 'analysis_detail_screen.dart';

/// All saved analyses for the signed-in user, newest first.  Tapping a row
/// opens the detail view with the 3D trajectory and decision.  Long-press
/// (or swipe) deletes.
class AnalysesScreen extends StatefulWidget {
  const AnalysesScreen({super.key, this.pitchId});

  /// When provided, only analyses for this pitch are shown.
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
        content: const Text('This permanently removes the saved trajectory and decision.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(backgroundColor: Theme.of(context).colorScheme.error),
            child: const Text('Delete'),
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
          const SnackBar(content: Text('Failed to delete analysis')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isPitchScoped = widget.pitchId != null;
    return Scaffold(
      appBar: isPitchScoped
          ? AppBar(title: const Text('Past Analyses'))
          : null,
      body: CustomScrollView(
        slivers: [
          if (!isPitchScoped)
            SliverAppBar(
              expandedHeight: 100,
              floating: false,
              pinned: true,
              flexibleSpace: FlexibleSpaceBar(
                title: Text(
                  'Analyses',
                  style: theme.textTheme.headlineMedium?.copyWith(
                    color: theme.colorScheme.onSurface,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                titlePadding: const EdgeInsets.only(left: 20, bottom: 16),
              ),
            ),
          SliverFillRemaining(
            child: StreamBuilder<List<AnalysisRecord>>(
              stream: _store.watchAnalyses(pitchId: widget.pitchId),
              builder: (context, snap) {
                if (snap.connectionState == ConnectionState.waiting) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snap.hasError) {
                  return _Error(message: 'Failed to load analyses', detail: '${snap.error}');
                }
                final records = snap.data ?? const <AnalysisRecord>[];
                if (records.isEmpty) {
                  return const _Empty();
                }
                return ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                  itemCount: records.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 10),
                  itemBuilder: (context, i) => _AnalysisTile(
                    record: records[i],
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => AnalysisDetailScreen(record: records[i]),
                      ),
                    ),
                    onDelete: () => _delete(records[i]),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _AnalysisTile extends StatelessWidget {
  const _AnalysisTile({required this.record, required this.onTap, required this.onDelete});

  final AnalysisRecord record;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final lbw = record.result.lbw;
    final decisionLabel = switch (lbw?.decision) {
      LbwDecisionKey.out => 'OUT',
      LbwDecisionKey.notOut => 'NOT OUT',
      LbwDecisionKey.umpiresCall => "UMPIRE'S CALL",
      _ => 'NO DECISION',
    };
    final (badgeBg, badgeFg) = switch (lbw?.decision) {
      LbwDecisionKey.out => (theme.colorScheme.errorContainer, theme.colorScheme.onErrorContainer),
      LbwDecisionKey.notOut => (theme.colorScheme.tertiaryContainer, theme.colorScheme.onTertiaryContainer),
      LbwDecisionKey.umpiresCall => (theme.colorScheme.secondaryContainer, theme.colorScheme.onSecondaryContainer),
      _ => (theme.colorScheme.surfaceContainerHighest, theme.colorScheme.onSurfaceVariant),
    };
    return Dismissible(
      key: ValueKey(record.id),
      direction: DismissDirection.endToStart,
      confirmDismiss: (_) async { onDelete(); return false; },
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 24),
        decoration: BoxDecoration(
          color: theme.colorScheme.error,
          borderRadius: BorderRadius.circular(16),
        ),
        child: const Icon(Icons.delete_outline, color: Colors.white, size: 24),
      ),
      child: Card(
        margin: EdgeInsets.zero,
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(
                    color: badgeBg,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    decisionLabel,
                    style: theme.textTheme.labelMedium?.copyWith(
                      color: badgeFg, fontWeight: FontWeight.w800, letterSpacing: 0.5,
                    ),
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        lbw?.reason ?? 'No reasoning available',
                        style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
                        maxLines: 2, overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 4),
                      Text(
                        _relative(record.createdAt),
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
                Icon(Icons.chevron_right_rounded, color: theme.colorScheme.onSurfaceVariant),
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
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 96, height: 96,
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainer,
                shape: BoxShape.circle,
              ),
              child: Icon(Icons.timeline_outlined, size: 44, color: theme.colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 20),
            Text('No analyses yet', style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            Text(
              'Analyses you run from a pitch will appear here.',
              style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}

class _Error extends StatelessWidget {
  const _Error({required this.message, required this.detail});
  final String message;
  final String detail;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 48, color: theme.colorScheme.error),
            const SizedBox(height: 12),
            Text(message, style: theme.textTheme.titleMedium),
            const SizedBox(height: 4),
            Text(detail, style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant), textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}
