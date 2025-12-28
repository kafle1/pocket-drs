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
        title: const Text('Delete Pitch?'),
        content: Text('Are you sure you want to delete "${pitch.name}"? This action cannot be undone.'),
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
        const SnackBar(content: Text('Please calibrate the pitch first'), behavior: SnackBarBehavior.floating),
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
                  ? const Center(child: Text('Pitch not found'))
                  : CustomScrollView(
                      slivers: [
                        SliverAppBar(
                          expandedHeight: 100,
                          floating: false,
                          pinned: true,
                          flexibleSpace: FlexibleSpaceBar(
                            title: Text(
                              pitch.name,
                              style: theme.textTheme.titleLarge?.copyWith(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            titlePadding: const EdgeInsets.only(left: 56, bottom: 16),
                          ),
                          actions: [
                            IconButton(
                              icon: const Icon(Icons.edit_outlined),
                              onPressed: _edit,
                              tooltip: 'Edit',
                            ),
                            IconButton(
                              icon: const Icon(Icons.delete_outline),
                              onPressed: _delete,
                              tooltip: 'Delete',
                            ),
                            const SizedBox(width: 8),
                          ],
                        ),
                        SliverPadding(
                          padding: const EdgeInsets.all(20),
                          sliver: SliverList(
                            delegate: SliverChildListDelegate([
                              _StatusBanner(calibrated: calibrated),
                              const SizedBox(height: 20),
                              if (calibrated) ...[
                                _ViewerCard(onView3D: _view3DFullscreen),
                                const SizedBox(height: 20),
                              ],
                              Text(
                                'Actions',
                                style: theme.textTheme.titleLarge?.copyWith(
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              const SizedBox(height: 12),
                              _ActionCard(
                                icon: Icons.analytics_outlined,
                                title: 'Analyze Delivery',
                                subtitle: calibrated
                                    ? 'Upload or record a ball video'
                                    : 'Calibrate the pitch first',
                                enabled: calibrated,
                                onTap: calibrated ? _analyze : null,
                                color: theme.colorScheme.primary,
                              ),
                              const SizedBox(height: 12),
                              _ActionCard(
                                icon: Icons.tune_outlined,
                                title: calibrated ? 'Re-calibrate' : 'Calibrate Pitch',
                                subtitle: 'Mark stumps and pitch corners for 3D tracking',
                                enabled: true,
                                onTap: _calibrate,
                                color: theme.colorScheme.secondary,
                              ),
                              const SizedBox(height: 20),
                              _InfoCard(pitch: pitch),
                            ]),
                          ),
                        ),
                      ],
                    ),
    );
  }
}

class _StatusBanner extends StatelessWidget {
  const _StatusBanner({required this.calibrated});
  final bool calibrated;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: calibrated
              ? [theme.colorScheme.tertiary, theme.colorScheme.tertiary.withValues(alpha: 0.7)]
              : [theme.colorScheme.error, theme.colorScheme.error.withValues(alpha: 0.7)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.2),
              shape: BoxShape.circle,
            ),
            child: Icon(
              calibrated ? Icons.check_circle : Icons.warning_amber_rounded,
              color: Colors.white,
              size: 28,
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  calibrated ? 'Ready to Analyze' : 'Needs Calibration',
                  style: theme.textTheme.titleMedium?.copyWith(
                    color: Colors.white,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  calibrated
                      ? 'Pitch is calibrated and ready for ball tracking'
                      : 'Calibrate to enable ball tracking analysis',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: Colors.white.withValues(alpha: 0.9),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ViewerCard extends StatelessWidget {
  const _ViewerCard({required this.onView3D});
  final VoidCallback onView3D;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return GestureDetector(
      onTap: onView3D,
      child: Container(
        height: 280,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          color: theme.colorScheme.surfaceContainerHighest,
          border: Border.all(
            color: theme.colorScheme.outline.withValues(alpha: 0.3),
          ),
        ),
        clipBehavior: Clip.antiAlias,
        child: Stack(
          children: [
            Pitch3DViewer(
              trajectoryPoints: [
                {'x': 0.0, 'y': 0.0, 'z': 0.5},
                {'x': 20.12, 'y': 0.0, 'z': 0.0},
              ],
            ),
            Positioned(
              left: 16,
              right: 16,
              bottom: 16,
              child: Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.7),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.white.withValues(alpha: 0.2)),
                ),
                child: Row(
                  children: [
                    Icon(Icons.view_in_ar, color: theme.colorScheme.primary, size: 24),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        'Tap to view 3D pitch',
                        style: theme.textTheme.titleSmall?.copyWith(
                          color: Colors.white,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    Icon(Icons.fullscreen, color: Colors.white.withValues(alpha: 0.8)),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ActionCard extends StatelessWidget {
  const _ActionCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.enabled,
    required this.color,
    this.onTap,
  });
  
  final IconData icon;
  final String title;
  final String subtitle;
  final bool enabled;
  final Color color;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      child: InkWell(
        onTap: enabled ? onTap : null,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Row(
            children: [
              Container(
                width: 56,
                height: 56,
                decoration: BoxDecoration(
                  color: enabled ? color.withValues(alpha: 0.15) : theme.colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(
                  icon,
                  color: enabled ? color : theme.colorScheme.onSurfaceVariant,
                  size: 28,
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
                        fontWeight: FontWeight.w700,
                        color: enabled ? null : theme.colorScheme.onSurfaceVariant,
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
                Icons.chevron_right_rounded,
                color: enabled ? theme.colorScheme.onSurfaceVariant : theme.colorScheme.outline,
                size: 28,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _InfoCard extends StatelessWidget {
  const _InfoCard({required this.pitch});
  final Pitch pitch;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.info_outline, color: theme.colorScheme.primary, size: 24),
                const SizedBox(width: 12),
                Text(
                  'Pitch Information',
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            _InfoRow(label: 'Name', value: pitch.name),
            const SizedBox(height: 12),
            _InfoRow(label: 'Created', value: _formatDateTime(pitch.createdAt)),
            const SizedBox(height: 12),
            _InfoRow(label: 'Last Updated', value: _formatDateTime(pitch.updatedAt)),
            const SizedBox(height: 12),
            _InfoRow(
              label: 'Status',
              value: pitch.isCalibrated ? 'Calibrated' : 'Not Calibrated',
            ),
          ],
        ),
      ),
    );
  }

  String _formatDateTime(DateTime dt) {
    return '${dt.day}/${dt.month}/${dt.year} at ${dt.hour}:${dt.minute.toString().padLeft(2, '0')}';
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 110,
          child: Text(
            label,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: theme.textTheme.bodyMedium?.copyWith(
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ],
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.error, required this.onRetry});
  final String error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 64, color: theme.colorScheme.error),
            const SizedBox(height: 16),
            Text(
              'Error',
              style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 8),
            Text(
              error,
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium,
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('Retry'),
            ),
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
        title: const Text('3D Pitch View', style: TextStyle(color: Colors.white)),
      ),
      extendBodyBehindAppBar: true,
      body: Pitch3DViewer(
        trajectoryPoints: [
          {'x': 0.0, 'y': 0.0, 'z': 0.5},
          {'x': 20.12, 'y': 0.0, 'z': 0.0},
        ],
      ),
    );
  }
}

