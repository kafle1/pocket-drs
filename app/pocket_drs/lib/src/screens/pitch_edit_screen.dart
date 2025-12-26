import 'package:flutter/material.dart';

import '../models/pitch.dart';

class PitchEditScreen extends StatefulWidget {
  const PitchEditScreen({
    super.key,
    this.initial,
  });

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

    final name = _name.text.trim();
    Navigator.of(context).pop(name);
  }

  @override
  Widget build(BuildContext context) {
    final isEdit = widget.initial != null;

    return Scaffold(
      appBar: AppBar(
        title: Text(isEdit ? 'Edit pitch' : 'New pitch'),
        actions: [
          TextButton(
            onPressed: _save,
            child: const Text('Save'),
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  'Give this pitch a memorable name.',
                  style: Theme.of(context).textTheme.bodyLarge,
                ),
                const SizedBox(height: 16),
                TextFormField(
                  controller: _name,
                  textInputAction: TextInputAction.done,
                  decoration: const InputDecoration(
                    labelText: 'Pitch name',
                    hintText: 'e.g., Home ground (North end)',
                    border: OutlineInputBorder(),
                  ),
                  validator: (v) {
                    final s = v?.trim() ?? '';
                    if (s.isEmpty) return 'Required';
                    if (s.length < 2) return 'Too short';
                    if (s.length > 60) return 'Too long';
                    return null;
                  },
                  onFieldSubmitted: (_) => _save(),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
