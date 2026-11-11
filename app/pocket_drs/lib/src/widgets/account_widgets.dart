import 'dart:async';

import 'package:flutter/material.dart';

import '../account/account.dart';
import '../theme/app_spacing.dart';

String planLine(Me me) => switch (me) {
  Me(isAdmin: true) => 'Admin, unlimited reviews',
  Me(left: null) => 'Premium, unlimited reviews',
  Me(:final left?, :final dailyLimit) =>
    '${left.clamp(0, dailyLimit)} of $dailyLimit free reviews left today',
};

/// When the free reviews come back, in the phone's own time; null when the server doesn't say.
String? resetLine(BuildContext context, Me me) {
  final at = me.resetsAt;
  if (at == null || me.left == null) return null;
  final now = DateTime.now();
  final time = TimeOfDay.fromDateTime(at).format(context);
  final today =
      at.year == now.year && at.month == now.month && at.day == now.day;
  return today ? 'More at $time' : 'More tomorrow at $time';
}

/// Free reviews left today and when more come, near the buttons that spend one.
class PlanStatus extends StatelessWidget {
  const PlanStatus({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return ValueListenableBuilder<Me?>(
      valueListenable: Account.instance.me,
      builder: (context, me, _) {
        if (me == null) return const SizedBox.shrink();
        final reset = resetLine(context, me);
        final used = me.usedUp;
        return Row(
          children: [
            Icon(
              used ? Icons.hourglass_empty : Icons.confirmation_number_outlined,
              size: 18,
              color: used ? scheme.error : scheme.onSurfaceVariant,
            ),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Text(
                [
                  used ? "No free reviews left today" : planLine(me),
                  ?reset,
                ].join('. '),
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: used ? scheme.error : scheme.onSurfaceVariant,
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

bool _usedUpOpen = false;

/// Shown when a review is turned away because today's free ones are gone.
Future<void> showUsedUp(BuildContext context) async {
  Account.instance.logEvent('trials_used_up');
  unawaited(Account.instance.refreshMe());
  // several session balls can hit the limit at once, so only one dialog shows
  if (_usedUpOpen) return;
  _usedUpOpen = true;
  final me = Account.instance.me.value;
  final reset = me == null ? null : resetLine(context, me);
  try {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('No free reviews left today'),
        content: Text(
          reset == null
              ? "You've used today's free reviews. More come back tomorrow."
              : "You've used today's free reviews. $reset.",
        ),
        actions: [
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('OK'),
          ),
        ],
      ),
    );
  } finally {
    _usedUpOpen = false;
  }
}
