import 'package:flutter/material.dart';

import '../models/pitch.dart';
import '../utils/pitch_store.dart';
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
        _error = e.toString();
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
        title: const Text('Pitches'),
        actions: [
          IconButton(
            tooltip: 'Settings',
            onPressed: () async {
              await Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const SettingsScreen()),
              );
            },
            icon: const Icon(Icons.settings),
          ),
          IconButton(
            tooltip: 'Reload',
            onPressed: _load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _createPitch,
        icon: const Icon(Icons.add),
        label: const Text('New pitch'),
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text('Something went wrong', style: theme.textTheme.titleLarge),
                        const SizedBox(height: 8),
                        Text(_error!),
                        const SizedBox(height: 16),
                        FilledButton(onPressed: _load, child: const Text('Try again')),
                      ],
                    ),
                  )
                : _pitches.isEmpty
                    ? Padding(
                        padding: const EdgeInsets.all(24),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Text('No pitches yet', style: theme.textTheme.headlineSmall),
                            const SizedBox(height: 8),
                            Text(
                              'Create a pitch, calibrate it, then record or import delivery clips for analysis.',
                              style: theme.textTheme.bodyLarge?.copyWith(
                                color: theme.colorScheme.onSurfaceVariant,
                              ),
                            ),
                            const SizedBox(height: 16),
                            FilledButton.icon(
                              onPressed: _createPitch,
                              icon: const Icon(Icons.add),
                              label: const Text('Create first pitch'),
                            ),
                          ],
                        ),
                      )
                    : ListView.separated(
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 96),
                        itemCount: _pitches.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 12),
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

    final statusText = pitch.isCalibrated ? 'Calibrated' : 'Needs calibration';
    final statusColor = pitch.isCalibrated
        ? theme.colorScheme.tertiary
        : theme.colorScheme.error;

    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      pitch.name,
                      style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        Container(
                          width: 10,
                          height: 10,
                          decoration: BoxDecoration(
                            color: statusColor,
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          statusText,
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: theme.colorScheme.onSurfaceVariant),
            ],
          ),
        ),
      ),
    );
  }
}
