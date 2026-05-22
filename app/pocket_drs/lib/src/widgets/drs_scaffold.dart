import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';

/// Real top safe-area inset and (text-scale-clamped) [TextScaler] for the
/// primary view.
///
/// Both headers sit in the Scaffold `appBar` slot, which clamps them to
/// `preferredSize.height`. A fixed height there overflows on devices with a
/// tall status bar (the inner [SafeArea] eats into the band) or under large
/// system fonts. Reading the live inset and scaler lets each `preferredSize`
/// below size its band to the real content height instead of a guess.
({double topInset, TextScaler textScaler}) _viewMetrics() {
  final views = WidgetsBinding.instance.platformDispatcher.views;
  if (views.isEmpty) {
    return (topInset: 0, textScaler: TextScaler.noScaling);
  }
  final mq = MediaQueryData.fromView(views.first);
  // Mirror the app-wide clamp in PocketDrsApp so the band matches what is
  // actually rendered.
  return (
    topInset: mq.padding.top,
    textScaler: mq.textScaler.clamp(maxScaleFactor: 1.3),
  );
}

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
  Size get preferredSize {
    final (:topInset, :textScaler) = _viewMetrics();
    // Eyebrow/action row collapses to the eyebrow line when there are no
    // interactive children; otherwise it is button-sized.
    final rowHeight = (actions.isNotEmpty || leading != null)
        ? kMinInteractiveDimension
        : textScaler.scale(10);
    final band = AppSpacing.xl // top padding
        + rowHeight
        + AppSpacing.md
        + textScaler.scale(36) * 1.05 // displaySmall title line box
        + AppSpacing.lg
        + 1; // divider
    return Size.fromHeight((topInset + band).ceilToDouble());
  }

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
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
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
            Container(height: 1, color: theme.colorScheme.outline),
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
  Size get preferredSize {
    final (:topInset, :textScaler) = _viewMetrics();
    final hasEyebrow = eyebrow != null && eyebrow!.isNotEmpty;
    final band = AppSpacing.sm // top padding
        + kMinInteractiveDimension // back-button row
        + AppSpacing.xs
        + (hasEyebrow ? textScaler.scale(10) + AppSpacing.sm : 0)
        + textScaler.scale(24) * 1.15 // headlineMedium title line box
        + AppSpacing.lg
        + 1; // divider
    return Size.fromHeight((topInset + band).ceilToDouble());
  }

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
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
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
            Container(height: 1, color: theme.colorScheme.outline),
          ],
        ),
      ),
    );
  }
}
