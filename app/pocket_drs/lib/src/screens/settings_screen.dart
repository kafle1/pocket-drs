import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../account/account.dart';
import '../reviews/reviews.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../theme/theme_controller.dart';
import '../utils/app_settings.dart';
import '../widgets/account_widgets.dart';
import '../widgets/pitch_setup.dart';
import 'admin_screen.dart';
import 'filming_guide_screen.dart';

const _version = '2.2.0';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _loading = true;
  SpeedUnit _speedUnit = SpeedUnit.kmh;
  bool _autoDeleteSource = false;
  late PitchSetup _pitch;
  bool _deleting = false;

  @override
  void initState() {
    super.initState();
    Account.instance.refreshMe();
    _load();
  }

  Future<void> _load() async {
    final unit = await AppSettings.getSpeedUnit();
    final autoDel = await AppSettings.getAutoDeleteSource();
    final pitch = await AppSettings.getPitchSetup();
    if (!mounted) return;
    setState(() {
      _speedUnit = unit;
      _autoDeleteSource = autoDel;
      _pitch = pitch;
      _loading = false;
    });
  }

  Future<void> _editPitch() async {
    final p = await showPitchSetup(context);
    if (p != null && mounted) setState(() => _pitch = p);
  }

  Future<void> _open(String url) async {
    final ok = await launchUrl(
      Uri.parse(url),
      mode: LaunchMode.externalApplication,
    ).catchError((_) => false);
    if (ok || !mounted) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text("Couldn't open $url")));
  }

  Future<void> _deleteAccount() async {
    final scheme = Theme.of(context).colorScheme;
    final sure = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete your account?'),
        content: const Text(
          'Your account, your free review count and every review saved on '
          "this phone are deleted. This can't be undone. Google will ask you "
          "to confirm it's you first.",
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Keep it'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: scheme.error,
              foregroundColor: scheme.onError,
            ),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (sure != true || !mounted) return;
    setState(() => _deleting = true);
    final messenger = ScaffoldMessenger.of(context);
    // success signs out, which drops every screen back to the sign-in gate
    final err = await Account.instance.deleteAccount(
      Reviews.instance.deleteAll,
    );
    if (err == null) return;
    messenger.showSnackBar(
      SnackBar(content: Text("Your account wasn't deleted. $err")),
    );
    if (mounted) setState(() => _deleting = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.only(bottom: AppSpacing.xxl),
              children: [
                const _Section('Account'),
                ValueListenableBuilder<Me?>(
                  valueListenable: Account.instance.me,
                  builder: (context, me, _) => Column(
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
                        leading: const Icon(Icons.confirmation_number_outlined),
                        title: Text(
                          me == null ? 'Loading your reviews' : planLine(me),
                        ),
                        subtitle: switch (me) {
                          final me? => switch (resetLine(me)) {
                            final r? => Text(r),
                            null => null,
                          },
                          null => null,
                        },
                      ),
                      if (me != null && me.isAdmin)
                        ListTile(
                          leading: const Icon(
                            Icons.admin_panel_settings_outlined,
                          ),
                          title: const Text('Admin'),
                          trailing: const Icon(Icons.chevron_right),
                          onTap: () => Navigator.of(context).push(
                            MaterialPageRoute<void>(
                              builder: (_) => const AdminScreen(),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
                ListTile(
                  leading: const Icon(Icons.logout),
                  title: const Text('Sign out'),
                  onTap: _deleting ? null : Account.instance.signOut,
                ),
                ListTile(
                  leading: Icon(
                    Icons.delete_outline,
                    color: Theme.of(context).colorScheme.error,
                  ),
                  title: Text(
                    'Delete account',
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                  trailing: _deleting
                      ? const SizedBox.square(
                          dimension: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : null,
                  onTap: _deleting ? null : _deleteAccount,
                ),
                const _Section('Your pitch'),
                ListTile(
                  leading: const Icon(Icons.straighten),
                  title: const Text('Pitch, stumps and ball'),
                  subtitle: Text(pitchSetupLine(_pitch)),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: _editPitch,
                ),
                const _Section('Display'),
                Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.lg,
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      ValueListenableBuilder<ThemeMode>(
                        valueListenable: ThemeController.instance.themeMode,
                        builder: (context, mode, _) =>
                            SegmentedButton<ThemeMode>(
                              expandedInsets: EdgeInsets.zero,
                              showSelectedIcon: false,
                              segments: const [
                                ButtonSegment(
                                  value: ThemeMode.system,
                                  label: Text('Auto'),
                                ),
                                ButtonSegment(
                                  value: ThemeMode.light,
                                  label: Text('Light'),
                                ),
                                ButtonSegment(
                                  value: ThemeMode.dark,
                                  label: Text('Dark'),
                                ),
                              ],
                              selected: {mode},
                              onSelectionChanged: (s) => ThemeController
                                  .instance
                                  .setThemeMode(s.first),
                            ),
                      ),
                      const SizedBox(height: AppSpacing.md),
                      SegmentedButton<SpeedUnit>(
                        expandedInsets: EdgeInsets.zero,
                        showSelectedIcon: false,
                        segments: const [
                          ButtonSegment(
                            value: SpeedUnit.kmh,
                            label: Text('km/h'),
                          ),
                          ButtonSegment(
                            value: SpeedUnit.mph,
                            label: Text('mph'),
                          ),
                        ],
                        selected: {_speedUnit},
                        onSelectionChanged: (s) {
                          setState(() => _speedUnit = s.first);
                          AppSettings.setSpeedUnit(s.first);
                        },
                      ),
                    ],
                  ),
                ),
                const _Section('Storage'),
                SwitchListTile(
                  value: _autoDeleteSource,
                  onChanged: (v) {
                    setState(() => _autoDeleteSource = v);
                    AppSettings.setAutoDeleteSource(v);
                  },
                  title: const Text('Delete recordings once sent'),
                  subtitle: const Text(
                    'Clips you record in the app are removed after the ball is '
                    'sent. The trimmed clip stays with its review.',
                  ),
                ),
                const _Section('Help'),
                ListTile(
                  leading: const Icon(Icons.help_outline),
                  title: const Text('How to film'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => const FilmingGuideScreen(),
                    ),
                  ),
                ),
                ListTile(
                  leading: const Icon(Icons.code),
                  title: const Text('Source code'),
                  subtitle: const Text('Free software under AGPL-3.0'),
                  trailing: const Icon(Icons.open_in_new),
                  onTap: () => _open('https://github.com/kafle1/pocket-drs'),
                ),
                ListTile(
                  leading: const Icon(Icons.privacy_tip_outlined),
                  title: const Text('Privacy policy'),
                  trailing: const Icon(Icons.open_in_new),
                  onTap: () => _open(
                    'https://github.com/kafle1/pocket-drs/blob/main/docs/privacy-policy.md',
                  ),
                ),
                const ListTile(
                  leading: Icon(Icons.info_outline),
                  title: Text('Pocket DRS'),
                  subtitle: Text('Version $_version'),
                ),
              ],
            ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section(this.label);
  final String label;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.xl,
        AppSpacing.lg,
        AppSpacing.sm,
      ),
      child: Text(
        label.toUpperCase(),
        style: AppTheme.caps(
          theme.textTheme.labelSmall,
        )?.copyWith(color: theme.colorScheme.primary),
      ),
    );
  }
}
