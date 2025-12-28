import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/pitch.dart';
import '../utils/pitch_store.dart';
import '../widgets/pitch_3d_viewer.dart';
import 'delivery_processing_screen.dart';
import 'pitch_calibration_screen.dart';
import 'pitch_edit_screen.dart';

class PitchDetailScreen extends StatefulWidget {
  const PitchDetailScreen({super.key, required this.pitchId});
  final String pitchId;

  @override
  State<PitchDetailScreen> createState() => _PitchDetailScreenState();
}

class _PitchDetailScreenState extends State<PitchDetailScreen> {
  final _store = PitchStore();
  bool _loading = true;
  String? _error;
  Pitch? _pitch;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final pitch = await _store.loadById(widget.pitchId);
      if (mounted) setState(() { _pitch = pitch; _loading = false; });
    } catch (e) {
      if (mounted) setState(() { _error = e.toString(); _loading = false; });
    }
  }

  Future<void> _edit() async {
    final pitch = _pitch;
    if (pitch == null) return;
    final name = await Navigator.of(context).push<String?>(
      MaterialPageRoute(builder: (_) => PitchEditScreen(initial: pitch)),
    );
    if (name != null && mounted) {
      await _store.update(pitch.copyWith(name: name, updatedAt: DateTime.now()));
      _load();
    }
  }

  Future<void> _delete() async {
    final pitch = _pitch;
    if (pitch == null) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete pitch?'),
        content: Text('Remove "${pitch.name}"?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(backgroundColor: Theme.of(context).colorScheme.error),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (ok == true && mounted) {
      await _store.delete(pitch.id);
      if (mounted) Navigator.pop(context);
    }
  }

  Future<void> _calibrate() async {
    final pitch = _pitch;
    if (pitch == null) return;
    final done = await Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => PitchCalibrationScreen(pitchId: pitch.id, pitchName: pitch.name)),
    );
    if (done == true && mounted) _load();
  }

  Future<void> _analyze() async {
    final pitch = _pitch;
    if (pitch == null || !pitch.isCalibrated) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Calibrate first'), behavior: SnackBarBehavior.floating),
      );
      return;
    }
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => DeliveryProcessingScreen(pitchId: pitch.id, pitchName: pitch.name)),
    );
  }

  void _view3DFullscreen() {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const _Fullscreen3DViewer()),
    );
  }

  @override
  Widget build(BuildContext context) {
    final pitch = _pitch;
    final calibrated = pitch?.isCalibrated ?? false;

    return Scaffold(
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: Text(pitch?.name ?? 'Pitch'),
        actions: [
          IconButton(icon: const Icon(Icons.edit_outlined), onPressed: _loading ? null : _edit),
          IconButton(icon: const Icon(Icons.delete_outline), onPressed: _loading ? null : _delete),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? _ErrorView(error: _error!, onRetry: _load)
              : pitch == null
                  ? const Center(child: Text('Not found'))
                  : _Content(
                      calibrated: calibrated,
                      onCalibrate: _calibrate,
                      onAnalyze: _analyze,
                      onView3D: _view3DFullscreen,
                    ),
    );
  }
}

class _Content extends StatelessWidget {
  const _Content({
    required this.calibrated,
    required this.onCalibrate,
    required this.onAnalyze,
    required this.onView3D,
  });
  final bool calibrated;
  final VoidCallback onCalibrate;
  final VoidCallback onAnalyze;
  final VoidCallback onView3D;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        // 3D Preview
        if (calibrated) ...[
          GestureDetector(
            onTap: onView3D,
            child: Container(
              height: 220,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(16),
                color: const Color(0xFF0A0A0A),
              ),
              clipBehavior: Clip.antiAlias,
              child: Stack(
                children: [
                  const Pitch3DViewer(),
                  Positioned(
                    right: 12,
                    top: 12,
                    child: Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(
                        color: Colors.black54,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: const Icon(Icons.fullscreen, color: Colors.white, size: 20),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 24),
        ],
        // Status
        _StatusCard(calibrated: calibrated, onCalibrate: onCalibrate),
        const SizedBox(height: 24),
        // Actions
        Text('Actions', style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600)),
        const SizedBox(height: 12),
        _ActionTile(
          icon: Icons.analytics_outlined,
          title: 'Analyze Delivery',
          subtitle: calibrated ? 'Upload video to analyze' : 'Calibration required',
          onTap: calibrated ? onAnalyze : null,
        ),
        const SizedBox(height: 8),
        _ActionTile(
          icon: Icons.sports_cricket,
          title: 'Quick Ball Analysis',
          subtitle: 'Upload ball image directly',
          onTap: calibrated ? () {} : null,
        ),
      ],
    );
  }
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({required this.calibrated, required this.onCalibrate});
  final bool calibrated;
  final VoidCallback onCalibrate;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainer,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 10,
                height: 10,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: calibrated ? const Color(0xFF4ADE80) : theme.colorScheme.error,
                ),
              ),
              const SizedBox(width: 10),
              Text(
                calibrated ? 'Calibrated' : 'Needs Calibration',
                style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            calibrated
                ? 'Ready to analyze deliveries'
                : 'Mark the pitch corners and stumps to enable analysis',
            style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: onCalibrate,
              icon: Icon(calibrated ? Icons.refresh : Icons.tune),
              label: Text(calibrated ? 'Recalibrate' : 'Start Calibration'),
            ),
          ),
        ],
      ),
    );
  }
}

class _ActionTile extends StatelessWidget {
  const _ActionTile({required this.icon, required this.title, required this.subtitle, this.onTap});
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final enabled = onTap != null;
    return Material(
      color: theme.colorScheme.surfaceContainer,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: enabled ? theme.colorScheme.primaryContainer : theme.colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(icon, color: enabled ? theme.colorScheme.primary : theme.colorScheme.outline),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: theme.textTheme.titleSmall?.copyWith(
                      color: enabled ? null : theme.colorScheme.outline,
                    )),
                    Text(subtitle, style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    )),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: enabled ? theme.colorScheme.onSurfaceVariant : theme.colorScheme.outline),
            ],
          ),
        ),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.error, required this.onRetry});
  final String error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Error', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 8),
            Text(error, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      ),
    );
  }
}

class _Fullscreen3DViewer extends StatelessWidget {
  const _Fullscreen3DViewer();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        iconTheme: const IconThemeData(color: Colors.white),
        systemOverlayStyle: SystemUiOverlayStyle.light,
      ),
      extendBodyBehindAppBar: true,
      body: const Pitch3DViewer(),
    );
  }
}
