import 'package:flutter/material.dart';

import '../models/pitch.dart';
import '../utils/pitch_store.dart';
import '../theme/app_spacing.dart';
import '../widgets/status_chip.dart';
import 'pitch_detail_screen.dart';
import 'pitch_edit_screen.dart';
import 'settings_screen.dart';

class PitchesScreen extends StatefulWidget {
  const PitchesScreen({super.key});

  @override
  State<PitchesScreen> createState() => _PitchesScreenState();
}

class _PitchesScreenState extends State<PitchesScreen> {
  final _store = PitchStore();

  bool _loading = true;
  String? _error;
  List<Pitch> _pitches = const <Pitch>[];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final pitches = await _store.loadAll();
      if (!mounted) return;
      setState(() {
        _pitches = pitches;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'Failed to load pitches';
        _loading = false;
      });
    }
  }

  Future<void> _createPitch() async {
    final name = await Navigator.of(context).push<String?>(
      MaterialPageRoute(builder: (_) => const PitchEditScreen()),
    );
    if (!mounted || name == null) return;

    final pitch = await _store.create(name: name);
    if (!mounted) return;

    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => PitchDetailScreen(pitchId: pitch.id)),
    );

    if (mounted) {
      await _load();
    }
  }

  Future<void> _openPitch(Pitch p) async {
    await _store.setActivePitchId(p.id);
    if (!mounted) return;

    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => PitchDetailScreen(pitchId: p.id)),
    );

    if (mounted) {
      await _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: theme.colorScheme.primary.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Icon(
                Icons.sports_cricket,
                color: theme.colorScheme.primary,
                size: 24,
              ),
            ),
            const SizedBox(width: AppSpacing.md),
            const Text('PocketDRS'),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Settings',
            onPressed: () async {
              await Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const SettingsScreen()),
              );
            },
            icon: const Icon(Icons.settings_outlined),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _createPitch,
        icon: const Icon(Icons.add_circle_outline),
        label: const Text('New Pitch'),
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(AppSpacing.lg),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(
                            Icons.error_outline,
                            size: 64,
                            color: theme.colorScheme.error,
                          ),
                          const SizedBox(height: AppSpacing.md),
                          Text(
                            'Something went wrong',
                            style: theme.textTheme.titleLarge,
                          ),
                          const SizedBox(height: AppSpacing.sm),
                          Text(
                            _error!,
                            style: theme.textTheme.bodyMedium?.copyWith(
                              color: theme.colorScheme.onSurfaceVariant,
                            ),
                            textAlign: TextAlign.center,
                          ),
                          const SizedBox(height: AppSpacing.lg),
                          FilledButton.icon(
                            onPressed: _load,
                            icon: const Icon(Icons.refresh),
                            label: const Text('Try Again'),
                          ),
                        ],
                      ),
                    ),
                  )
                : _pitches.isEmpty
                    ? Center(
                        child: Padding(
                          padding: const EdgeInsets.all(AppSpacing.xl),
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(
                                Icons.sports_cricket,
                                size: 80,
                                color: theme.colorScheme.primary.withValues(alpha: 0.3),
                              ),
                              const SizedBox(height: AppSpacing.lg),
                              Text(
                                'No Pitches Yet',
                                style: theme.textTheme.headlineSmall?.copyWith(
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              const SizedBox(height: AppSpacing.md),
                              Text(
                                'Create and calibrate a pitch to start tracking deliveries with DRS technology',
                                style: theme.textTheme.bodyLarge?.copyWith(
                                  color: theme.colorScheme.onSurfaceVariant,
                                ),
                                textAlign: TextAlign.center,
                              ),
                              const SizedBox(height: AppSpacing.xl),
                              FilledButton.icon(
                                onPressed: _createPitch,
                                icon: const Icon(Icons.add_circle_outline),
                                label: const Text('Create First Pitch'),
                              ),
                            ],
                          ),
                        ),
                      )
                    : ListView.separated(
                        padding: const EdgeInsets.fromLTRB(
                          AppSpacing.md,
                          AppSpacing.md,
                          AppSpacing.md,
                          96,
                        ),
                        itemCount: _pitches.length,
                        separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.md),
                        itemBuilder: (context, i) {
                          final p = _pitches[i];
                          return _PitchCard(
                            pitch: p,
                            onTap: () => _openPitch(p),
                          );
                        },
                      ),
      ),
    );
  }
}

class _PitchCard extends StatelessWidget {
  const _PitchCard({
    required this.pitch,
    required this.onTap,
  });

  final Pitch pitch;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    final isCalibrated = pitch.isCalibrated;
    final statusColor = isCalibrated
        ? theme.colorScheme.tertiary
        : theme.colorScheme.error;

    return Card(
      elevation: 2,
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(AppSpacing.md),
                decoration: BoxDecoration(
                  color: theme.colorScheme.primary.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(AppRadius.md),
                ),
                child: Icon(
                  Icons.sports_cricket,
                  color: theme.colorScheme.primary,
                  size: 32,
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      pitch.name,
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    StatusChip(
                      label: isCalibrated ? 'Calibrated' : 'Needs Calibration',
                      color: statusColor,
                      icon: isCalibrated ? Icons.check_circle : Icons.warning,
                    ),
                  ],
                ),
              ),
              Icon(
                Icons.chevron_right,
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
