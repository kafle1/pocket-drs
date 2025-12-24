import 'package:flutter/material.dart';

import '../analysis/calibration_config.dart';
import '../utils/calibration_store.dart';

class CalibrationScreen extends StatefulWidget {
  const CalibrationScreen({
    super.key,
    required this.initial,
  });

  final CalibrationConfig initial;

  @override
  State<CalibrationScreen> createState() => _CalibrationScreenState();
}

class _CalibrationScreenState extends State<CalibrationScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _pitchLength;
  late final TextEditingController _pitchWidth;
  late final TextEditingController _stumpHeight;
  late final TextEditingController _cameraHeight;
  late final TextEditingController _cameraDistance;
  late final TextEditingController _cameraOffset;

  String? _error;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    final c = widget.initial;
    _pitchLength = TextEditingController(text: c.pitchLengthM.toStringAsFixed(2));
    _pitchWidth = TextEditingController(text: c.pitchWidthM.toStringAsFixed(2));
    _stumpHeight = TextEditingController(text: c.stumpHeightM.toStringAsFixed(3));
    _cameraHeight = TextEditingController(text: c.cameraHeightM.toStringAsFixed(2));
    _cameraDistance = TextEditingController(text: c.cameraDistanceToStumpsM.toStringAsFixed(2));
    _cameraOffset = TextEditingController(text: c.cameraLateralOffsetM.toStringAsFixed(2));
  }

  @override
  void dispose() {
    _pitchLength.dispose();
    _pitchWidth.dispose();
    _stumpHeight.dispose();
    _cameraHeight.dispose();
    _cameraDistance.dispose();
    _cameraOffset.dispose();
    super.dispose();
  }

  double? _parse(String s) {
    final v = double.tryParse(s.trim());
    if (v == null) return null;
    if (v.isNaN || v.isInfinite) return null;
    return v;
  }

  CalibrationConfig? _readConfig() {
    final pitch = _parse(_pitchLength.text);
    final width = _parse(_pitchWidth.text);
    final stump = _parse(_stumpHeight.text);
    final camH = _parse(_cameraHeight.text);
    final camD = _parse(_cameraDistance.text);
    final camO = _parse(_cameraOffset.text);

    if (pitch == null || width == null || stump == null || camH == null || camD == null || camO == null) {
      return null;
    }

    return CalibrationConfig(
      pitchLengthM: pitch,
      pitchWidthM: width,
      stumpHeightM: stump,
      cameraHeightM: camH,
      cameraDistanceToStumpsM: camD,
      cameraLateralOffsetM: camO,
      pitchCalibration: widget.initial.pitchCalibration,
    );
  }

  Future<void> _saveAndContinue() async {
    setState(() {
      _error = null;
      _saving = true;
    });

    try {
      final ok = _formKey.currentState?.validate() ?? false;
      if (!ok) return;

      final cfg = _readConfig();
      if (cfg == null) {
        throw StateError('Please enter valid numeric values');
      }

      final errors = cfg.validate();
      if (errors.isNotEmpty) {
        throw StateError(errors.join('\n'));
      }

      await CalibrationStore().save(cfg);

      if (!mounted) return;
      Navigator.of(context).pop(cfg);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
      });
    } finally {
      if (mounted) {
        setState(() => _saving = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Calibration'),
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
                  'Set physical measurements before tracking.',
                  style: theme.textTheme.titleMedium,
                ),
                const SizedBox(height: 8),
                Text(
                  'These values are saved and reused for future clips on this device.',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                const SizedBox(height: 16),
                Expanded(
                  child: ListView(
                    children: [
                      _field(
                        controller: _pitchLength,
                        label: 'Pitch length (m)',
                        helper: 'Stump-to-stump distance. Default: 20.12',
                        validator: (v) => _validateNumber(v, min: 10, max: 30),
                      ),
                      const SizedBox(height: 12),
                      _field(
                        controller: _pitchWidth,
                        label: 'Pitch width (m)',
                        helper: 'Approx. 3.05 (10 ft). Used for pitch-plane mapping.',
                        validator: (v) => _validateNumber(v, min: 1.5, max: 6),
                      ),
                      const SizedBox(height: 12),
                      _field(
                        controller: _stumpHeight,
                        label: 'Stump height (m)',
                        helper: 'Default: 0.711',
                        validator: (v) => _validateNumber(v, min: 0.4, max: 1.2),
                      ),
                      const SizedBox(height: 12),
                      _field(
                        controller: _cameraHeight,
                        label: 'Camera height (m)',
                        helper: 'From ground to camera lens.',
                        validator: (v) => _validateNumber(v, min: 0.2, max: 10),
                      ),
                      const SizedBox(height: 12),
                      _field(
                        controller: _cameraDistance,
                        label: 'Camera distance to stumps (m)',
                        helper: 'Horizontal distance from camera to striker stumps.',
                        validator: (v) => _validateNumber(v, min: 1, max: 60),
                      ),
                      const SizedBox(height: 12),
                      _field(
                        controller: _cameraOffset,
                        label: 'Camera lateral offset (m)',
                        helper: '0 = centered on pitch line. +off-side / -leg-side.',
                        validator: (v) => _validateNumber(v, min: -20, max: 20),
                      ),
                      if (_error != null) ...[
                        const SizedBox(height: 12),
                        Text(
                          _error!,
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: theme.colorScheme.error,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: _saving ? null : _saveAndContinue,
                  icon: _saving
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.check),
                  label: const Text('Continue to tracking'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

String? _validateNumber(String? value, {required double min, required double max}) {
  if (value == null) return 'Required';
  final v = double.tryParse(value.trim());
  if (v == null || v.isNaN || v.isInfinite) return 'Enter a number';
  if (v < min || v > max) return 'Must be between $min and $max';
  return null;
}

Widget _field({
  required TextEditingController controller,
  required String label,
  required String helper,
  required String? Function(String?) validator,
}) {
  return TextFormField(
    controller: controller,
    keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
    decoration: InputDecoration(
      labelText: label,
      helperText: helper,
      border: const OutlineInputBorder(),
    ),
    validator: validator,
  );
}
