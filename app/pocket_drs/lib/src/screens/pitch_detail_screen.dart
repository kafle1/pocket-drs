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
    final theme = Theme.of(context);

    return Scaffold(
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? _ErrorView(error: _error!, onRetry: _load)
              : pitch == null
                  ? const Center(child: Text('Not found'))
                  : CustomScrollView(
                      slivers: [
                        SliverAppBar.large(
                          title: Text(pitch.name),
                          actions: [
                            IconButton(
                              icon: const Icon(Icons.edit_outlined),
                              onPressed: _edit,
                              tooltip: 'Edit Name',
                            ),
                            IconButton(
                              icon: const Icon(Icons.delete_outline),
                              onPressed: _delete,
                              tooltip: 'Delete Pitch',
                            ),
                            const SizedBox(width: 8),
                          ],
                        ),
                        SliverPadding(
                          padding: const EdgeInsets.all(16),
                          sliver: SliverList(
                            delegate: SliverChildListDelegate([
                              if (calibrated) ...[
                                GestureDetector(
                                  onTap: _view3DFullscreen,
                                  child: Container(
                                    height: 240,
                                    decoration: BoxDecoration(
                                      borderRadius: BorderRadius.circular(24),
                                      color: const Color(0xFF0F172A),
                                      boxShadow: [
                                        BoxShadow(
                                          color: Colors.black.withOpacity(0.2),
                                          blurRadius: 12,
                                          offset: const Offset(0, 4),
                                        ),
                                      ],
                                    ),
                                    clipBehavior: Clip.antiAlias,
                                    child: Stack(
                                      children: [
                                        const Pitch3DViewer(),
                                        Positioned(
                                          right: 16,
                                          top: 16,
                                          child: Container(
                                            padding: const EdgeInsets.all(8),
                                            decoration: BoxDecoration(
                                              color: Colors.white.withOpacity(0.1),
                                              borderRadius: BorderRadius.circular(12),
                                              border: Border.all(
                                                color: Colors.white.withOpacity(0.2),
                                              ),
                                            ),
                                            child: const Icon(Icons.fullscreen, color: Colors.white, size: 24),
                                          ),
                                        ),
                                        Positioned(
                                          left: 16,
                                          bottom: 16,
                                          child: Container(
                                            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                                            decoration: BoxDecoration(
                                              color: theme.colorScheme.primary,
                                              borderRadius: BorderRadius.circular(20),
                                            ),
                                            child: const Text(
                                              '3D PREVIEW',
                                              style: TextStyle(
                                                color: Colors.white,
                                                fontSize: 10,
                                                fontWeight: FontWeight.bold,
                                                letterSpacing: 1,
                                              ),
                                            ),
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 24),
                              ],
                              _StatusCard(calibrated: calibrated, onCalibrate: _calibrate),
                              const SizedBox(height: 32),
                              Text(
                                'Actions',
                                style: theme.textTheme.titleMedium?.copyWith(
                                  fontWeight: FontWeight.bold,
                                  color: theme.colorScheme.onSurface,
                                ),
                              ),
                              const SizedBox(height: 16),
                              _ActionTile(
                                icon: Icons.movie_filter_outlined,
                                title: 'Analyze Delivery',
                                subtitle: calibrated ? 'Upload video to analyze' : 'Calibration required',
                                onTap: calibrated ? _analyze : null,
                                isPrimary: true,
                              ),
                              const SizedBox(height: 12),
                              _ActionTile(
                                icon: Icons.sports_cricket_outlined,
                                title: 'Quick Ball Analysis',
                                subtitle: 'Coming soon',
                                onTap: null, // Disabled for now
                              ),
                            ]),
                          ),
                        ),
                      ],
                    ),
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
    final color = calibrated ? const Color(0xFF10B981) : theme.colorScheme.error;
    
    return Card(
      elevation: 0,
      color: theme.colorScheme.surfaceContainer,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(24),
        side: BorderSide(
          color: theme.colorScheme.outlineVariant.withOpacity(0.3),
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: color.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: color.withOpacity(0.2)),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 8,
                        height: 8,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: color,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        calibrated ? 'CALIBRATED' : 'NEEDS CALIBRATION',
                        style: TextStyle(
                          color: color,
                          fontSize: 11,
                          fontWeight: FontWeight.bold,
                          letterSpacing: 0.5,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Text(
              calibrated
                  ? 'Ready for Action'
                  : 'Setup Required',
              style: theme.textTheme.titleLarge?.copyWith(
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              calibrated
                  ? 'This pitch is calibrated and ready to analyze deliveries with high precision.'
                  : 'Mark the pitch corners and stumps to enable Hawk-Eye analysis for this ground.',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
                height: 1.5,
              ),
            ),
            const SizedBox(height: 24),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: onCalibrate,
                style: FilledButton.styleFrom(
                  backgroundColor: calibrated ? theme.colorScheme.secondary : theme.colorScheme.primary,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                ),
                icon: Icon(calibrated ? Icons.tune : Icons.build_circle_outlined),
                label: Text(calibrated ? 'Recalibrate Pitch' : 'Start Calibration'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ActionTile extends StatelessWidget {
  const _ActionTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    this.onTap,
    this.isPrimary = false,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback? onTap;
  final bool isPrimary;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final enabled = onTap != null;
    
    return Card(
      elevation: 0,
      color: isPrimary ? theme.colorScheme.primaryContainer.withOpacity(0.3) : theme.colorScheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(
          color: isPrimary 
              ? theme.colorScheme.primary.withOpacity(0.2) 
              : theme.colorScheme.outlineVariant.withOpacity(0.5),
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Row(
            children: [
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: enabled 
                      ? (isPrimary ? theme.colorScheme.primary : theme.colorScheme.secondaryContainer)
                      : theme.colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(
                  icon,
                  color: enabled 
                      ? (isPrimary ? theme.colorScheme.onPrimary : theme.colorScheme.onSecondaryContainer)
                      : theme.colorScheme.outline,
                  size: 24,
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                        color: enabled ? theme.colorScheme.onSurface : theme.colorScheme.outline,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      subtitle,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              Icon(
                Icons.arrow_forward_ios,
                size: 16,
                color: enabled ? theme.colorScheme.onSurfaceVariant : theme.colorScheme.outline.withOpacity(0.5),
              ),
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
