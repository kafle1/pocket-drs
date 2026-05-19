import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';

/// Editorial header used in place of [AppBar] on top-level screens.
///
/// Structure:
///   ┌─────────────────────────────────────────┐
///   │  EYEBROW                          ⋯     │
///   │  Display Title                          │
///   │  ────────────────────────────────────── │
///   └─────────────────────────────────────────┘
///
/// Eyebrow is a wide-tracked ALL CAPS label; the title is set in the display
/// face. A single hairline divides the header from content.
class DrsHeader extends StatelessWidget implements PreferredSizeWidget {
  const DrsHeader({
    super.key,
    required this.title,
    this.eyebrow,
    this.actions = const <Widget>[],
    this.leading,
  });

  final String title;
  final String? eyebrow;
  final List<Widget> actions;
  final Widget? leading;

  @override
  Size get preferredSize => const Size.fromHeight(132);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SafeArea(
      bottom: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.xl,
          AppSpacing.xl,
          AppSpacing.lg,
          0,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (leading != null) ...[
                  leading!,
                  const SizedBox(width: AppSpacing.md),
                ],
                Expanded(
                  child: Text(
                    (eyebrow ?? 'POCKET DRS').toUpperCase(),
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                ),
                ...actions,
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              title,
              style: theme.textTheme.displaySmall,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            const SizedBox(height: AppSpacing.lg),
            Container(
              height: 1,
              color: theme.colorScheme.outline,
            ),
          ],
        ),
      ),
    );
  }
}

/// Stacked back-arrow header for sub-pages.
class DrsSubHeader extends StatelessWidget implements PreferredSizeWidget {
  const DrsSubHeader({
    super.key,
    required this.title,
    this.eyebrow,
    this.actions = const <Widget>[],
    this.onBack,
  });

  final String title;
  final String? eyebrow;
  final List<Widget> actions;
  final VoidCallback? onBack;

  @override
  Size get preferredSize => const Size.fromHeight(120);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SafeArea(
      bottom: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.md,
          AppSpacing.sm,
          AppSpacing.md,
          0,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                IconButton(
                  onPressed: onBack ?? () => Navigator.of(context).maybePop(),
                  icon: const Icon(Icons.arrow_back, size: 20),
                  tooltip: 'Back',
                ),
                const Spacer(),
                ...actions,
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            Padding(
              padding: const EdgeInsets.only(left: AppSpacing.md),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (eyebrow != null && eyebrow!.isNotEmpty)
                    Text(
                      eyebrow!.toUpperCase(),
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  if (eyebrow != null && eyebrow!.isNotEmpty)
                    const SizedBox(height: AppSpacing.sm),
                  Text(
                    title,
                    style: theme.textTheme.headlineMedium,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            Container(
              height: 1,
              color: theme.colorScheme.outline,
            ),
          ],
        ),
      ),
    );
  }
}
