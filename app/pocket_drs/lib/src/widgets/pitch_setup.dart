import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../utils/app_settings.dart';

String pitchSetupLine(PitchSetup p) =>
    '${pitchLabel(p.lengthM)} pitch, ${p.stumps.label.toLowerCase()} stumps, '
    '${p.ball.label.toLowerCase()} ball';

/// Lets the player set the pitch length, stumps and ball; returns the saved choice.
Future<PitchSetup?> showPitchSetup(BuildContext context) async {
  final current = await AppSettings.getPitchSetup();
  if (!context.mounted) return null;
  final next = await showModalBottomSheet<PitchSetup>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => _PitchSetupSheet(initial: current),
  );
  if (next == null) return null;
  await AppSettings.setPitchLength(next.lengthM);
  await AppSettings.setStumpSize(next.stumps);
  await AppSettings.setBallType(next.ball);
  return next;
}

class _PitchSetupSheet extends StatefulWidget {
  const _PitchSetupSheet({required this.initial});
  final PitchSetup initial;

  @override
  State<_PitchSetupSheet> createState() => _PitchSetupSheetState();
}

class _PitchSetupSheetState extends State<_PitchSetupSheet> {
  late StumpSize _stumps = widget.initial.stumps;
  late BallType _ball = widget.initial.ball;
  // a preset in yards, or null for a length typed in
  late int? _preset = AppSettings.pitchPresetYards
      .where(
        (y) => (y * AppSettings.yardM - widget.initial.lengthM).abs() < 0.01,
      )
      .firstOrNull;
  late final _custom = TextEditingController(
    text: _preset == null
        ? (widget.initial.lengthM / AppSettings.yardM).toStringAsFixed(1)
        : '',
  );

  @override
  void dispose() {
    _custom.dispose();
    super.dispose();
  }

  static final _minYd = AppSettings.minPitchM / AppSettings.yardM;
  static final _maxYd = AppSettings.maxPitchM / AppSettings.yardM;

  // commas too, since many keyboards use them as the decimal mark; NaN fails the range check
  double? get _lengthM {
    final p = _preset;
    if (p != null) return p * AppSettings.yardM;
    final yd = double.tryParse(_custom.text.trim().replaceAll(',', '.'));
    return yd != null && yd >= _minYd && yd <= _maxYd
        ? yd * AppSettings.yardM
        : null;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final length = _lengthM;
    Widget heading(String title, String help) => Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: theme.textTheme.titleMedium),
          const SizedBox(height: 2),
          Text(
            help,
            style: theme.textTheme.bodySmall?.copyWith(
              color: scheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            0,
            AppSpacing.lg,
            AppSpacing.lg,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('Your pitch', style: theme.textTheme.titleLarge),
              const SizedBox(height: AppSpacing.lg),
              heading('Length', 'Stumps to stumps. A full pitch is 22 yards.'),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: [
                  for (final y in AppSettings.pitchPresetYards)
                    ChoiceChip(
                      label: Text('$y yd'),
                      selected: _preset == y,
                      onSelected: (_) => setState(() => _preset = y),
                    ),
                  ChoiceChip(
                    label: const Text('Other'),
                    selected: _preset == null,
                    onSelected: (_) => setState(() => _preset = null),
                  ),
                ],
              ),
              if (_preset == null) ...[
                const SizedBox(height: AppSpacing.md),
                TextField(
                  controller: _custom,
                  autofocus: true,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: InputDecoration(
                    labelText: 'Length',
                    suffixText: 'yd',
                    helperText: length == null
                        ? null
                        : '${length.toStringAsFixed(2)} m',
                    errorText: length == null
                        ? 'Enter ${_minYd.ceil()} to ${_maxYd.floor()} yards'
                        : null,
                  ),
                  onChanged: (_) => setState(() {}),
                ),
              ],
              const SizedBox(height: AppSpacing.xl),
              heading('Stumps', 'Height by width, the whole set of three.'),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: [
                  for (final s in StumpSize.values)
                    ChoiceChip(
                      label: Text('${s.label}, ${s.inches}'),
                      selected: _stumps == s,
                      onSelected: (_) => setState(() => _stumps = s),
                    ),
                ],
              ),
              const SizedBox(height: AppSpacing.xl),
              heading(
                'Ball',
                'Taped tennis means a tennis ball wrapped in tape.',
              ),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: [
                  for (final b in BallType.values)
                    ChoiceChip(
                      label: Text(b.label),
                      selected: _ball == b,
                      onSelected: (_) => setState(() => _ball = b),
                    ),
                ],
              ),
              const SizedBox(height: AppSpacing.lg),
              FilledButton(
                onPressed: length == null
                    ? null
                    : () => Navigator.pop<PitchSetup>(context, (
                        lengthM: length,
                        stumps: _stumps,
                        ball: _ball,
                      )),
                child: const Text('Save'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The pitch in use, one tap from changing it.
class PitchSetupChip extends StatefulWidget {
  const PitchSetupChip({super.key});

  @override
  State<PitchSetupChip> createState() => _PitchSetupChipState();
}

class _PitchSetupChipState extends State<PitchSetupChip> {
  PitchSetup? _setup;

  @override
  void initState() {
    super.initState();
    AppSettings.getPitchSetup().then((p) {
      if (mounted) setState(() => _setup = p);
    });
  }

  Future<void> _edit() async {
    final p = await showPitchSetup(context);
    if (p != null && mounted) setState(() => _setup = p);
  }

  @override
  Widget build(BuildContext context) {
    final p = _setup;
    return ActionChip(
      avatar: const Icon(Icons.straighten, size: 18),
      label: Text(
        p == null ? 'Pitch' : '${pitchLabel(p.lengthM)} · ${p.stumps.label}',
        overflow: TextOverflow.ellipsis,
      ),
      tooltip: 'Pitch length, stumps and ball',
      onPressed: _edit,
    );
  }
}
