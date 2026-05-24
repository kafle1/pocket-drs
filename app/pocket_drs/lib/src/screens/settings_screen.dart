import 'package:flutter/material.dart';
import '../services/auth_service.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../theme/theme_controller.dart';
import '../utils/app_settings.dart';
import '../widgets/drs_button.dart';
import '../widgets/drs_scaffold.dart';
import '../widgets/section_label.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _auth = AuthService();
  bool _loading = true;
  ThemeMode _themeMode = ThemeMode.system;
  SpeedUnit _speedUnit = SpeedUnit.kmh;
  bool _autoDeleteSource = false;
  String _serverUrl = '';
  late final TextEditingController _serverCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _serverCtrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final themeMode = ThemeController.instance.themeMode.value;
    final url = await AppSettings.getServerUrl();
    final unit = await AppSettings.getSpeedUnit();
    final autoDel = await AppSettings.getAutoDeleteSource();
    if (!mounted) return;
    setState(() {
      _themeMode = themeMode;
      _speedUnit = unit;
      _autoDeleteSource = autoDel;
      _serverUrl = url;
      _serverCtrl.text = url;
      _loading = false;
    });
  }

  Future<void> _setSpeedUnit(SpeedUnit unit) async {
    setState(() => _speedUnit = unit);
    await AppSettings.setSpeedUnit(unit);
  }

  Future<void> _setAutoDelete(bool v) async {
    setState(() => _autoDeleteSource = v);
    await AppSettings.setAutoDeleteSource(v);
  }

  Future<void> _saveServerUrl(String value) async {
    final v = value.trim();
    if (v.isEmpty || v == _serverUrl) return;
    await AppSettings.setServerUrl(v);
    if (!mounted) return;
    setState(() => _serverUrl = v);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Server URL updated')),
    );
  }

  Future<void> _signOut() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Sign out?'),
        content: const Text('You will return to the sign-in screen.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('CANCEL')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('SIGN OUT')),
        ],
      ),
    );
    if (confirmed == true) await _auth.signOut();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: const DrsHeader(eyebrow: 'CONFIGURE', title: 'Settings'),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.xl,
                AppSpacing.lg,
                AppSpacing.xl,
                AppSpacing.xxl,
              ),
              children: [
                _AccountBlock(
                  userName: _auth.userName ?? 'Unknown',
                  userEmail: _auth.userEmail ?? '',
                  photoUrl: _auth.userPhotoUrl,
                  onSignOut: _signOut,
                ),
                const SizedBox(height: AppSpacing.xxl),
                const SectionLabel(label: 'APPEARANCE'),
                _ThemeBlock(
                  themeMode: _themeMode,
                  onChanged: (mode) {
                    setState(() => _themeMode = mode);
                    ThemeController.instance.setThemeMode(mode);
                  },
                ),
                const SizedBox(height: AppSpacing.xxl),
                const SectionLabel(label: 'UNITS'),
                _SpeedUnitBlock(
                  unit: _speedUnit,
                  onChanged: _setSpeedUnit,
                ),
                const SizedBox(height: AppSpacing.xxl),
                const SectionLabel(label: 'STORAGE'),
                _AutoDeleteBlock(
                  value: _autoDeleteSource,
                  onChanged: _setAutoDelete,
                ),
                const SizedBox(height: AppSpacing.xxl),
                const SectionLabel(label: 'BACKEND'),
                _ServerBlock(
                  controller: _serverCtrl,
                  onSave: _saveServerUrl,
                ),
                const SizedBox(height: AppSpacing.xxl),
                const SectionLabel(label: 'ABOUT'),
                _AboutBlock(),
              ],
            ),
    );
  }
}

class _AccountBlock extends StatelessWidget {
  const _AccountBlock({
    required this.userName,
    required this.userEmail,
    this.photoUrl,
    required this.onSignOut,
  });

  final String userName;
  final String userEmail;
  final String? photoUrl;
  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SectionLabel(label: 'ACCOUNT'),
        Row(
          children: [
            Container(
              width: 56,
              height: 56,
              decoration: BoxDecoration(
                color: scheme.surfaceContainer,
                border: Border.all(color: scheme.outline, width: 1),
                image: photoUrl != null
                    ? DecorationImage(image: NetworkImage(photoUrl!), fit: BoxFit.cover)
                    : null,
              ),
              child: photoUrl == null
                  ? Icon(Icons.person, color: scheme.onSurfaceVariant)
                  : null,
            ),
            const SizedBox(width: AppSpacing.lg),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(userName, style: theme.textTheme.titleLarge),
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    userEmail,
                    style: theme.textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant),
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.lg),
        DrsButton(
          label: 'SIGN OUT',
          style: DrsButtonStyle.secondary,
          icon: Icons.logout,
          onPressed: onSignOut,
        ),
      ],
    );
  }
}

class _ThemeBlock extends StatelessWidget {
  const _ThemeBlock({required this.themeMode, required this.onChanged});
  final ThemeMode themeMode;
  final ValueChanged<ThemeMode> onChanged;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Row(
      children: [
        for (final entry in const [
          (ThemeMode.dark, 'DARK', Icons.dark_mode_outlined),
          (ThemeMode.light, 'LIGHT', Icons.light_mode_outlined),
          (ThemeMode.system, 'AUTO', Icons.brightness_auto_outlined),
        ])
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(right: entry.$1 == ThemeMode.system ? 0 : AppSpacing.sm),
              child: _ThemeOption(
                mode: entry.$1,
                label: entry.$2,
                icon: entry.$3,
                selected: themeMode == entry.$1,
                onTap: () => onChanged(entry.$1),
                scheme: scheme,
              ),
            ),
          ),
      ],
    );
  }
}

class _ThemeOption extends StatelessWidget {
  const _ThemeOption({
    required this.mode,
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
    required this.scheme,
  });

  final ThemeMode mode;
  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;
  final ColorScheme scheme;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected ? scheme.onSurface : Colors.transparent,
      shape: RoundedRectangleBorder(
        side: BorderSide(color: scheme.outline, width: 1),
        borderRadius: BorderRadius.circular(AppRadius.sm),
      ),
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.lg),
          child: Column(
            children: [
              Icon(
                icon,
                size: 18,
                color: selected ? scheme.surface : scheme.onSurface,
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                label,
                style: TextStyle(
                  color: selected ? scheme.surface : scheme.onSurface,
                  fontSize: 10.5,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.4,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SpeedUnitBlock extends StatelessWidget {
  const _SpeedUnitBlock({required this.unit, required this.onChanged});
  final SpeedUnit unit;
  final ValueChanged<SpeedUnit> onChanged;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Row(
      children: [
        for (final entry in const [
          (SpeedUnit.kmh, 'KM/H'),
          (SpeedUnit.mph, 'MPH'),
        ])
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(right: entry.$1 == SpeedUnit.mph ? 0 : AppSpacing.sm),
              child: Material(
                color: unit == entry.$1 ? scheme.onSurface : Colors.transparent,
                shape: RoundedRectangleBorder(
                  side: BorderSide(color: scheme.outline, width: 1),
                  borderRadius: BorderRadius.circular(AppRadius.sm),
                ),
                child: InkWell(
                  onTap: () => onChanged(entry.$1),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: AppSpacing.lg),
                    child: Center(
                      child: Text(
                        entry.$2,
                        style: TextStyle(
                          color: unit == entry.$1 ? scheme.surface : scheme.onSurface,
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 1.4,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}

class _AutoDeleteBlock extends StatelessWidget {
  const _AutoDeleteBlock({required this.value, required this.onChanged});
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return Material(
      color: Colors.transparent,
      shape: RoundedRectangleBorder(
        side: BorderSide(color: scheme.outline, width: 1),
        borderRadius: BorderRadius.circular(AppRadius.sm),
      ),
      child: SwitchListTile(
        value: value,
        onChanged: onChanged,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.lg,
          vertical: AppSpacing.xs,
        ),
        title: Text(
          'Auto-delete recordings after analysis',
          style: theme.textTheme.bodyMedium,
        ),
        subtitle: Text(
          'Removes the source video from the phone once a result is shown. Pre-existing camera-roll videos are never touched.',
          style: theme.textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant),
        ),
      ),
    );
  }
}

class _ServerBlock extends StatelessWidget {
  const _ServerBlock({required this.controller, required this.onSave});
  final TextEditingController controller;
  final Future<void> Function(String) onSave;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Where the analysis pipeline runs.',
          style: theme.textTheme.bodyMedium?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        TextField(
          controller: controller,
          autocorrect: false,
          keyboardType: TextInputType.url,
          decoration: const InputDecoration(
            labelText: 'SERVER URL',
            hintText: 'http://192.168.1.10:8000',
            prefixIcon: Icon(Icons.link, size: 18),
          ),
          onSubmitted: onSave,
        ),
        const SizedBox(height: AppSpacing.md),
        DrsButton(
          label: 'SAVE',
          icon: Icons.check,
          onPressed: () => onSave(controller.text),
        ),
      ],
    );
  }
}

class _AboutBlock extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 48,
          height: 48,
          decoration: BoxDecoration(
            color: theme.colorScheme.onSurface,
            borderRadius: BorderRadius.circular(AppRadius.xs),
          ),
          child: Icon(Icons.sports_cricket, color: theme.colorScheme.surface, size: 24),
        ),
        const SizedBox(width: AppSpacing.lg),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Pocket DRS', style: theme.textTheme.titleLarge),
              const SizedBox(height: AppSpacing.xs),
              Text(
                'Single-view 3D trajectory & LBW decision review.',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                'VERSION 1.0.0 · BETA',
                style: AppTypography.mono(theme.textTheme.labelSmall)?.copyWith(
                  color: AppColors.signalRed,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
