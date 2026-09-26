import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../theme/app_spacing.dart';
import '../theme/theme_controller.dart';
import '../utils/app_settings.dart';

const _version = '2.0.0';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _loading = true;
  ThemeMode _themeMode = ThemeMode.system;
  SpeedUnit _speedUnit = SpeedUnit.kmh;
  bool _autoDeleteSource = false;
  double _pitchLength = AppSettings.fullPitchM;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final themeMode = ThemeController.instance.themeMode.value;
    final unit = await AppSettings.getSpeedUnit();
    final autoDel = await AppSettings.getAutoDeleteSource();
    final pitch = await AppSettings.getPitchLength();
    if (!mounted) return;
    setState(() {
      _themeMode = themeMode;
      _speedUnit = unit;
      _autoDeleteSource = autoDel;
      _pitchLength = pitch;
      _loading = false;
    });
  }

  void _setThemeMode(ThemeMode mode) {
    setState(() => _themeMode = mode);
    ThemeController.instance.setThemeMode(mode);
  }

  Future<void> _setSpeedUnit(SpeedUnit unit) async {
    setState(() => _speedUnit = unit);
    await AppSettings.setSpeedUnit(unit);
  }

  Future<void> _setAutoDelete(bool v) async {
    setState(() => _autoDeleteSource = v);
    await AppSettings.setAutoDeleteSource(v);
  }

  Future<void> _editPitchLength() async {
    final v = await showDialog<double>(
      context: context,
      builder: (_) => _PitchLengthDialog(initial: _pitchLength),
    );
    if (v == null || !mounted) return;
    setState(() => _pitchLength = v);
    await AppSettings.setPitchLength(v);
  }

  Future<void> _open(String url) =>
      launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: CustomScrollView(
        slivers: [
          const SliverAppBar.large(title: Text('Settings')),
          if (_loading)
            const SliverFillRemaining(
              child: Center(child: CircularProgressIndicator()),
            )
          else
            SliverPadding(
              padding: const EdgeInsets.only(bottom: AppSpacing.xxl),
              sliver: SliverList(
                delegate: SliverChildListDelegate([
                  const _SectionHeader('Appearance'),
                  const ListTile(title: Text('Theme')),
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.lg,
                    ),
                    child: SegmentedButton<ThemeMode>(
                      expandedInsets: EdgeInsets.zero,
                      segments: const [
                        ButtonSegment(
                          value: ThemeMode.system,
                          label: Text('System'),
                          icon: Icon(Icons.brightness_auto_outlined),
                        ),
                        ButtonSegment(
                          value: ThemeMode.light,
                          label: Text('Light'),
                          icon: Icon(Icons.light_mode_outlined),
                        ),
                        ButtonSegment(
                          value: ThemeMode.dark,
                          label: Text('Dark'),
                          icon: Icon(Icons.dark_mode_outlined),
                        ),
                      ],
                      selected: {_themeMode},
                      onSelectionChanged: (s) => _setThemeMode(s.first),
                    ),
                  ),
                  const _SectionHeader('Units'),
                  const ListTile(title: Text('Speed')),
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.lg,
                    ),
                    child: SegmentedButton<SpeedUnit>(
                      expandedInsets: EdgeInsets.zero,
                      segments: const [
                        ButtonSegment(
                          value: SpeedUnit.kmh,
                          label: Text('km/h'),
                        ),
                        ButtonSegment(value: SpeedUnit.mph, label: Text('mph')),
                      ],
                      selected: {_speedUnit},
                      onSelectionChanged: (s) => _setSpeedUnit(s.first),
                    ),
                  ),
                  const _SectionHeader('Pitch'),
                  ListTile(
                    title: const Text('Pitch length'),
                    subtitle: Text(
                      _pitchLength == AppSettings.fullPitchM
                          ? '${_pitchLength.toStringAsFixed(2)} m, full size'
                          : '${_pitchLength.toStringAsFixed(2)} m',
                    ),
                    trailing: const Icon(Icons.edit_outlined),
                    onTap: _editPitchLength,
                  ),
                  if (!kIsWeb) ...[
                    const _SectionHeader('Storage'),
                    SwitchListTile(
                      value: _autoDeleteSource,
                      onChanged: _setAutoDelete,
                      title: const Text('Delete recordings after analysis'),
                      subtitle: const Text(
                        'Clips you record in the app are removed once you '
                        'leave the result.',
                      ),
                    ),
                  ],
                  const _SectionHeader('About'),
                  const ListTile(
                    title: Text('Pocket DRS'),
                    subtitle: Text('Version $_version'),
                  ),
                  ListTile(
                    title: const Text('Source code'),
                    subtitle: const Text('Free software under AGPL-3.0'),
                    trailing: const Icon(Icons.open_in_new),
                    onTap: () => _open('https://github.com/kafle1/pocket-drs'),
                  ),
                  ListTile(
                    title: const Text('Privacy policy'),
                    trailing: const Icon(Icons.open_in_new),
                    onTap: () => _open(
                      'https://github.com/kafle1/pocket-drs/blob/main/docs/privacy-policy.md',
                    ),
                  ),
                ]),
              ),
            ),
        ],
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.lg,
        AppSpacing.lg,
        AppSpacing.xs,
      ),
      child: Text(
        label,
        style: theme.textTheme.titleSmall?.copyWith(
          color: theme.colorScheme.primary,
        ),
      ),
    );
  }
}

class _PitchLengthDialog extends StatefulWidget {
  const _PitchLengthDialog({required this.initial});

  final double initial;

  @override
  State<_PitchLengthDialog> createState() => _PitchLengthDialogState();
}

class _PitchLengthDialogState extends State<_PitchLengthDialog> {
  late final _controller = TextEditingController(
    text: widget.initial.toStringAsFixed(2),
  );

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  // commas too, since many keyboards use them as the decimal mark; NaN fails the range check
  double? get _value {
    final v = double.tryParse(_controller.text.trim().replaceAll(',', '.'));
    return v != null && v >= AppSettings.minPitchM && v <= AppSettings.maxPitchM
        ? v
        : null;
  }

  @override
  Widget build(BuildContext context) {
    final v = _value;
    return AlertDialog(
      title: const Text('Pitch length'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Measure from the batter\'s stumps to the bowler\'s stumps. '
            'This sets the scale for ball speed and the 3D view.',
          ),
          const SizedBox(height: AppSpacing.lg),
          TextField(
            controller: _controller,
            autofocus: true,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(
              suffixText: 'm',
              helperText: 'A full pitch is 20.12 m (22 yards)',
              errorText: v == null
                  ? 'Enter ${AppSettings.minPitchM.toStringAsFixed(0)} to '
                        '${AppSettings.maxPitchM.toStringAsFixed(0)} m'
                  : null,
            ),
            onChanged: (_) => setState(() {}),
            onSubmitted: (_) {
              if (_value != null) Navigator.pop(context, _value);
            },
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, AppSettings.fullPitchM),
          child: const Text('Full size'),
        ),
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: v == null ? null : () => Navigator.pop(context, v),
          child: const Text('Save'),
        ),
      ],
    );
  }
}
