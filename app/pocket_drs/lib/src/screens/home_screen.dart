import 'package:flutter/material.dart';

import '../api/analysis_result.dart';
import '../reviews/reviews.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../utils/app_settings.dart';
import '../widgets/account_widgets.dart';
import '../widgets/verdict.dart';
import 'analyze_screen.dart';
import 'filming_guide_screen.dart';
import 'review_screen.dart';
import 'session_screen.dart';
import 'settings_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  SpeedUnit _unit = SpeedUnit.kmh;

  @override
  void initState() {
    super.initState();
    _loadUnit();
  }

  Future<void> _loadUnit() async {
    final u = await AppSettings.getSpeedUnit();
    if (mounted) setState(() => _unit = u);
  }

  void _push(Widget screen) => Navigator.of(context)
      .push(MaterialPageRoute<void>(builder: (_) => screen))
      // the unit may have changed in settings
      .then((_) => _loadUnit());

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Pocket DRS'),
        actions: [
          IconButton(
            tooltip: 'Settings',
            onPressed: () => _push(const SettingsScreen()),
            icon: const Icon(Icons.settings_outlined),
          ),
        ],
      ),
      body: ListenableBuilder(
        listenable: Reviews.instance,
        builder: (context, _) {
          final reviews = Reviews.instance.items;
          return CustomScrollView(
            slivers: [
              SliverPadding(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg,
                  AppSpacing.sm,
                  AppSpacing.lg,
                  0,
                ),
                sliver: SliverList.list(
                  children: [
                    const PlanStatus(),
                    const SizedBox(height: AppSpacing.lg),
                    _SessionPanel(
                      onTap: () =>
                          openWithGuide(context, const SessionScreen()),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    OutlinedButton.icon(
                      onPressed: () =>
                          openWithGuide(context, const AnalyzeScreen()),
                      icon: const Icon(Icons.video_library_outlined),
                      label: const Text('Check a clip you have'),
                    ),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton.icon(
                        onPressed: () => _push(const FilmingGuideScreen()),
                        icon: const Icon(Icons.help_outline),
                        label: const Text('How to film'),
                      ),
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    Text(
                      'YOUR REVIEWS',
                      style: AppTheme.caps(
                        theme.textTheme.labelSmall,
                      )?.copyWith(color: scheme.onSurfaceVariant),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                  ],
                ),
              ),
              if (reviews.isEmpty)
                const SliverFillRemaining(
                  hasScrollBody: false,
                  child: _NoReviews(),
                )
              else
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(
                    AppSpacing.lg,
                    0,
                    AppSpacing.lg,
                    AppSpacing.xxl,
                  ),
                  sliver: SliverList.separated(
                    itemCount: reviews.length,
                    separatorBuilder: (_, _) =>
                        const SizedBox(height: AppSpacing.sm),
                    itemBuilder: (context, i) => _ReviewRow(
                      review: reviews[i],
                      unit: _unit,
                      onTap: () => _push(ReviewScreen(review: reviews[i])),
                    ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}

class _SessionPanel extends StatelessWidget {
  const _SessionPanel({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return Material(
      color: scheme.primary,
      borderRadius: BorderRadius.circular(AppRadius.lg),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Start a session',
                      style: theme.textTheme.titleLarge?.copyWith(
                        color: scheme.onPrimary,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      'Phone on a tripod behind the bowler. Mark the stumps '
                      'once, then press Ball after each delivery.',
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: scheme.onPrimary.withValues(alpha: 0.85),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Icon(Icons.arrow_forward, color: scheme.onPrimary),
            ],
          ),
        ),
      ),
    );
  }
}

class _NoReviews extends StatelessWidget {
  const _NoReviews();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.lg,
        AppSpacing.lg,
        AppSpacing.xxl,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.sports_cricket, size: 32, color: scheme.outline),
          const SizedBox(height: AppSpacing.md),
          Text('No reviews yet', style: theme.textTheme.titleMedium),
          const SizedBox(height: AppSpacing.xs),
          Text(
            'Every ball you check lands here and stays on this phone, so you '
            'can open its call again or share it later.',
            style: theme.textTheme.bodyMedium?.copyWith(
              color: scheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }
}

String _when(BuildContext context, DateTime t) {
  final now = DateTime.now();
  final days = DateTime(
    now.year,
    now.month,
    now.day,
  ).difference(DateTime(t.year, t.month, t.day)).inDays;
  final time = TimeOfDay.fromDateTime(t).format(context);
  return switch (days) {
    0 => 'Today $time',
    1 => 'Yesterday $time',
    _ => '${MaterialLocalizations.of(context).formatShortMonthDay(t)}, $time',
  };
}

class _ReviewRow extends StatelessWidget {
  const _ReviewRow({
    required this.review,
    required this.unit,
    required this.onTap,
  });
  final Review review;
  final SpeedUnit unit;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final r = review;
    final result = r.state == ReviewState.done ? r.result : null;
    final lbw = result?.lbw;
    final colour = AppColors.verdict(lbw?.decision);
    // an unsure call is outlined here too, never filled like a sure one
    final sure = (lbw?.confidence ?? 1) >= surePoint;
    final fill = sure ? colour : null;
    final m = result?.metrics;
    final speed = unit == SpeedUnit.kmh ? m?.speedKmh : m?.speedMph;
    final (title, failed) = switch (r.state) {
      ReviewState.sending => ('Sending', false),
      ReviewState.checking => (
        r.pct == null ? 'Checking' : 'Checking, ${r.pct}%',
        false,
      ),
      ReviewState.done when lbw != null => (lbw.decision.label, false),
      ReviewState.done => ('No call', false),
      ReviewState.failed => ("Wasn't checked", true),
      ReviewState.expired => ('Cleared by the server', true),
    };
    final detail = [
      _when(context, r.createdAt),
      if (speed != null) '${speed.toStringAsFixed(0)} ${unit.label}',
      if (r.handedness == 'left') 'Left-hander',
    ].join('  ·  ');
    return Dismissible(
      key: ObjectKey(r),
      direction: r.busy ? DismissDirection.none : DismissDirection.endToStart,
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: AppSpacing.xl),
        decoration: BoxDecoration(
          color: scheme.errorContainer,
          borderRadius: BorderRadius.circular(AppRadius.lg),
        ),
        child: Icon(Icons.delete_outline, color: scheme.onErrorContainer),
      ),
      confirmDismiss: (_) => confirmDeleteReview(context),
      onDismissed: (_) => Reviews.instance.delete(r),
      child: Card(
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Row(
              children: [
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: fill ?? scheme.surfaceContainerHigh,
                    borderRadius: BorderRadius.circular(AppRadius.sm),
                    border: fill == null && colour != null
                        ? Border.all(color: colour, width: 2)
                        : null,
                  ),
                  child: r.busy
                      ? Padding(
                          padding: const EdgeInsets.all(12),
                          child: CircularProgressIndicator(
                            strokeWidth: 2.5,
                            color: scheme.primary,
                          ),
                        )
                      : Icon(
                          switch ((failed, lbw?.decision)) {
                            (true, _) => Icons.error_outline,
                            (_, LbwDecisionKey.out) => Icons.close,
                            (_, LbwDecisionKey.notOut) => Icons.check,
                            (_, LbwDecisionKey.umpiresCall) =>
                              Icons.drag_handle,
                            _ => Icons.remove,
                          },
                          color: fill != null
                              ? AppColors.onVerdict(fill)
                              : failed
                              ? scheme.error
                              : colour ?? scheme.onSurfaceVariant,
                        ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleMedium?.copyWith(
                          color: failed ? scheme.error : null,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        detail,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.tabular(
                          theme.textTheme.bodySmall,
                        )?.copyWith(color: scheme.onSurfaceVariant),
                      ),
                    ],
                  ),
                ),
                Icon(Icons.chevron_right, color: scheme.outline),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
