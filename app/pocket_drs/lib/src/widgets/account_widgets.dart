import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

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
  Account.instance.logEvent('contact_admin_tapped');
  final to = Account.instance.me.value?.contactEmail ?? kAdminEmail;
  final opened = await launchUrl(
    Uri.parse('mailto:$to?subject=PocketDRS%20premium'),
  ).catchError((_) => false);
  if (opened || !context.mounted) return;
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
        return Card.filled(
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

bool _usedUpOpen = false;

/// Shown when a review is turned away because the free ones are gone.
Future<void> showUsedUp(BuildContext context) async {
  Account.instance.logEvent('trials_used_up');
  unawaited(Account.instance.refreshMe());
  // several session balls can hit the limit at once, so only one dialog shows
  if (_usedUpOpen) return;
  _usedUpOpen = true;
  try {
    await showDialog<void>(
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
  } finally {
    _usedUpOpen = false;
  }
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
