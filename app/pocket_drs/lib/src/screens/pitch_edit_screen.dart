import 'package:flutter/material.dart';
import '../models/pitch.dart';
import '../theme/app_spacing.dart';
import '../widgets/drs_button.dart';
import '../widgets/drs_scaffold.dart';

class PitchEditScreen extends StatefulWidget {
  const PitchEditScreen({super.key, this.initial});

  final Pitch? initial;

  @override
  State<PitchEditScreen> createState() => _PitchEditScreenState();
}

class _PitchEditScreenState extends State<PitchEditScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _name;

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(text: widget.initial?.name ?? '');
  }

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  void _save() {
    final ok = _formKey.currentState?.validate() ?? false;
    if (!ok) return;
    Navigator.of(context).pop(_name.text.trim());
  }

  @override
  Widget build(BuildContext context) {
    final isEdit = widget.initial != null;
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;

    return Scaffold(
      appBar: DrsSubHeader(
        eyebrow: isEdit ? 'EDIT' : 'CREATE',
        title: isEdit ? 'Edit Pitch' : 'New Pitch',
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xl),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: AppSpacing.xl),
              Text(
                'NAME',
                style: theme.textTheme.labelMedium?.copyWith(
                  color: scheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              TextFormField(
                controller: _name,
                textInputAction: TextInputAction.done,
                autofocus: !isEdit,
                style: theme.textTheme.titleLarge,
                decoration: const InputDecoration(
                  hintText: 'Home Ground, MCG, Lord\'s',
                ),
                validator: (v) {
                  final s = v?.trim() ?? '';
                  if (s.isEmpty) return 'Enter a name';
                  if (s.length < 2) return 'Too short';
                  if (s.length > 60) return 'Too long (max 60)';
                  return null;
                },
                onFieldSubmitted: (_) => _save(),
              ),
              const SizedBox(height: AppSpacing.xl),
              Container(
                padding: const EdgeInsets.all(AppSpacing.lg),
                decoration: BoxDecoration(
                  border: Border.all(color: scheme.outline, width: 1),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(Icons.info_outline, size: 16, color: scheme.onSurfaceVariant),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: Text(
                        'You\'ll calibrate the pitch corners and stumps in the next step.',
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: scheme.onSurfaceVariant,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.xxl),
              DrsButton(
                label: isEdit ? 'UPDATE' : 'CONTINUE',
                icon: Icons.arrow_forward,
                onPressed: _save,
              ),
              if (isEdit) ...[
                const SizedBox(height: AppSpacing.md),
                DrsButton(
                  label: 'CANCEL',
                  style: DrsButtonStyle.secondary,
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ],
              const SizedBox(height: AppSpacing.xl),
            ],
          ),
        ),
      ),
    );
  }
}
