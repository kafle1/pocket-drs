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
        _error = 'Failed to load pitches';
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    
    return Scaffold(
      body: CustomScrollView(
        slivers: [
          SliverAppBar.large(
            title: const Text('Pitches'),
            actions: [
              IconButton(
                icon: const Icon(Icons.settings_outlined),
                onPressed: () {
                  Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const SettingsScreen()),
                  );
                },
              ),
              const SizedBox(width: 8),
            ],
          ),
          if (_loading)
            const SliverFillRemaining(
              child: Center(child: CircularProgressIndicator()),
            )
          else if (_error != null)
            SliverFillRemaining(
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.error_outline, size: 48, color: theme.colorScheme.error),
                    const SizedBox(height: 16),
                    Text(_error!, style: theme.textTheme.bodyLarge),
                    const SizedBox(height: 16),
                    FilledButton.tonal(
                      onPressed: _load,
                      child: const Text('Retry'),
                    ),
                  ],
                ),
              ),
            )
          else if (_pitches.isEmpty)
            SliverFillRemaining(
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.sports_cricket_outlined, size: 64, color: theme.colorScheme.outline),
                    const SizedBox(height: 16),
                    Text(
                      'No pitches yet',
                      style: theme.textTheme.titleLarge?.copyWith(color: theme.colorScheme.outline),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Add a pitch to get started',
                      style: theme.textTheme.bodyMedium,
                    ),
                  ],
                ),
              ),
            )
          else
            SliverPadding(
              padding: const EdgeInsets.all(16),
              sliver: SliverList(
                delegate: SliverChildBuilderDelegate(
                  (context, index) {
                    final pitch = _pitches[index];
                    return _PitchCard(
                      pitch: pitch,
                      onTap: () async {
                        await Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => PitchDetailScreen(pitchId: pitch.id),
                          ),
                        );
                        _load();
                      },
                    );
                  },
                  childCount: _pitches.length,
                ),
              ),
            ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () async {
          await Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => const PitchEditScreen()),
          );
          _load();
        },
        icon: const Icon(Icons.add),
        label: const Text('New Pitch'),
      ),
    );
  }
}

class _PitchCard extends StatelessWidget {
  final Pitch pitch;
  final VoidCallback onTap;

  const _PitchCard({required this.pitch, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isCalibrated = pitch.isCalibrated;
    
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(
                    child: Text(
                      pitch.name,
                      style: theme.textTheme.titleLarge,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(
                      color: isCalibrated 
                          ? theme.colorScheme.primaryContainer 
                          : theme.colorScheme.surfaceContainerHighest,
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Text(
                      isCalibrated ? 'Calibrated' : 'Not Calibrated',
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: isCalibrated 
                            ? theme.colorScheme.onPrimaryContainer 
                            : theme.colorScheme.onSurfaceVariant,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Icon(Icons.calendar_today_outlined, size: 16, color: theme.colorScheme.outline),
                  const SizedBox(width: 8),
                  Text(
                    'Updated ${pitch.updatedAt.toString().split(' ')[0]}',
                    style: theme.textTheme.bodyMedium,
                  ),
                  const Spacer(),
                  Icon(Icons.arrow_forward, size: 16, color: theme.colorScheme.primary),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
