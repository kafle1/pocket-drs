import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// Label-over-value stat block used across the app for any numeric / unit
/// pair. Tabular-figures so digits align in columns.
class TelemetryStat extends StatelessWidget {
  const TelemetryStat({
    super.key,
    required this.label,
    required this.value,
    this.unit,
    this.large = false,
  });

  final String label;
  final String value;
  final String? unit;
  final bool large;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final valueStyle = (large
            ? theme.textTheme.displaySmall
            : theme.textTheme.headlineSmall)
        ?.copyWith(fontWeight: FontWeight.w800);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label.toUpperCase(),
          style: theme.textTheme.labelSmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: AppSpacing.sm),
        Row(
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            Text(value, style: AppTypography.mono(valueStyle)),
            if (unit != null) ...[
              const SizedBox(width: 4),
              Text(
                unit!,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ],
        ),
      ],
    );
  }
}

/// Inline horizontal stat row that lays out 2–4 telemetry stats with
/// hairline dividers between them.
class TelemetryRow extends StatelessWidget {
  const TelemetryRow({super.key, required this.stats});
  final List<TelemetryStat> stats;

  @override
  Widget build(BuildContext context) {
    final divider = Container(
      width: 1,
      height: 32,
      color: Theme.of(context).colorScheme.outline,
    );
    final children = <Widget>[];
    for (var i = 0; i < stats.length; i++) {
      children.add(Expanded(child: stats[i]));
      if (i < stats.length - 1) {
        children.add(Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
          child: divider,
        ));
      }
    }
    return Row(crossAxisAlignment: CrossAxisAlignment.center, children: children);
  }
}
