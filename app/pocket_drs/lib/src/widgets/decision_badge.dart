import 'package:flutter/material.dart';

import '../api/analysis_result.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';

/// Cricket DRS decision pill. Sharp-cornered, ALL CAPS, broadcast colour:
/// • OUT — signal red
/// • NOT OUT — pitch green
/// • UMPIRE'S CALL — caution amber
/// • — — neutral hairline outline
class DecisionBadge extends StatelessWidget {
  const DecisionBadge({
    super.key,
    required this.decision,
    this.size = DecisionBadgeSize.medium,
  });

  final LbwDecisionKey? decision;
  final DecisionBadgeSize size;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final (label, accent) = switch (decision) {
      LbwDecisionKey.out => ('OUT', AppColors.decisionOut(isDark)),
      LbwDecisionKey.notOut => ('NOT OUT', AppColors.decisionNotOut(isDark)),
      LbwDecisionKey.umpiresCall => ("UMPIRE'S CALL", AppColors.decisionUmpire(isDark)),
      _ => ('NO DECISION', scheme.onSurfaceVariant),
    };

    final padH = switch (size) {
      DecisionBadgeSize.small => AppSpacing.md,
      DecisionBadgeSize.medium => AppSpacing.lg,
      DecisionBadgeSize.large => AppSpacing.xl,
    };
    final padV = switch (size) {
      DecisionBadgeSize.small => AppSpacing.xs + 2,
      DecisionBadgeSize.medium => AppSpacing.sm,
      DecisionBadgeSize.large => AppSpacing.md,
    };
    final fontSize = switch (size) {
      DecisionBadgeSize.small => 10.0,
      DecisionBadgeSize.medium => 12.0,
      DecisionBadgeSize.large => 16.0,
    };
    final tracking = switch (size) {
      DecisionBadgeSize.small => 1.2,
      DecisionBadgeSize.medium => 1.6,
      DecisionBadgeSize.large => 2.4,
    };

    return Container(
      padding: EdgeInsets.symmetric(horizontal: padH, vertical: padV),
      decoration: BoxDecoration(
        color: accent,
        borderRadius: BorderRadius.circular(AppRadius.xs),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: AppColors.inkBlack,
          fontSize: fontSize,
          fontWeight: FontWeight.w800,
          letterSpacing: tracking,
        ),
      ),
    );
  }
}

enum DecisionBadgeSize { small, medium, large }
