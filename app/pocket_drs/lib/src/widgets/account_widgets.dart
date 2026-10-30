import 'package:flutter/material.dart';

import '../account/account.dart';
import '../api/pocket_drs_api.dart';
import '../screens/admin_screen.dart';
import '../theme/app_spacing.dart';

String planLine(Me me) => switch (me) {
  Me(isAdmin: true) => 'Admin, unlimited reviews',
  Me(left: null) => 'Premium, unlimited reviews',
  Me(:final left?, :final freeLimit) =>
    '${left.clamp(0, freeLimit)} of $freeLimit free reviews left',
};

Future<void> contactAdmin(BuildContext context) async {
  final opened = await Account.instance.contactAdmin();
  if (opened || !context.mounted) return;
  final to = Account.instance.me.value?.contactEmail ?? kAdminEmail;
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text('No email app found. Write to $to for premium.')),
  );
}

/// Free reviews left, the used-up message, or the plan, near the analyse button.
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
        if (!me.usedUp) {
          return Text(
            planLine(me),
            style: theme.textTheme.bodyMedium?.copyWith(
              color: scheme.onSurfaceVariant,
            ),
          );
        }
        return Card.outlined(
          margin: EdgeInsets.zero,
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(kUsedUp, style: theme.textTheme.bodyMedium),
                const SizedBox(height: AppSpacing.md),
                FilledButton.icon(
                  icon: const Icon(Icons.mail_outline),
                  label: const Text('Contact admin'),
                  onPressed: () => contactAdmin(context),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// Shown when the server turns a review away because the free ones are gone.
Future<void> showUsedUp(BuildContext context) {
  return showDialog<void>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('No free reviews left'),
      content: const Text(kUsedUp),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext),
          child: const Text('Close'),
        ),
        FilledButton(
          onPressed: () {
            Navigator.pop(dialogContext);
            contactAdmin(context);
          },
          child: const Text('Contact admin'),
        ),
      ],
    ),
  );
}

/// Who is signed in, their plan, Admin when allowed, and Sign out.
Future<void> showAccountSheet(BuildContext context) {
  Account.instance.refreshMe();
  final nav = Navigator.of(context);
  return showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    isScrollControlled: true,
    builder: (sheetContext) => SafeArea(
      child: SingleChildScrollView(
        child: ValueListenableBuilder<Me?>(
          valueListenable: Account.instance.me,
          builder: (_, me, _) => Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                leading: const Icon(Icons.account_circle_outlined),
                title: Text(
                  me == null || me.name.isEmpty ? 'Signed in' : me.name,
                  overflow: TextOverflow.ellipsis,
                ),
                subtitle: me == null || me.email.isEmpty
                    ? null
                    : Text(me.email, overflow: TextOverflow.ellipsis),
              ),
              ListTile(
                leading: const Icon(Icons.workspace_premium_outlined),
                title: Text(me == null ? 'Loading your plan' : planLine(me)),
              ),
              if (me != null && me.isAdmin)
                ListTile(
                  leading: const Icon(Icons.admin_panel_settings_outlined),
                  title: const Text('Admin'),
                  onTap: () {
                    Navigator.pop(sheetContext);
                    nav.push(
                      MaterialPageRoute<void>(
                        builder: (_) => const AdminScreen(),
                      ),
                    );
                  },
                ),
              if (me != null && me.left != null)
                ListTile(
                  leading: const Icon(Icons.mail_outline),
                  title: const Text('Contact admin'),
                  subtitle: const Text('Ask for premium access'),
                  onTap: () => contactAdmin(sheetContext),
                ),
              ListTile(
                leading: const Icon(Icons.logout),
                title: const Text('Sign out'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  Account.instance.signOut();
                },
              ),
              const SizedBox(height: AppSpacing.md),
            ],
          ),
        ),
      ),
    ),
  );
}
