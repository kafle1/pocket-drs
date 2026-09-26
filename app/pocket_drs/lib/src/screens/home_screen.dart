import 'package:flutter/material.dart';

import '../api/pocket_drs_api.dart';
import '../theme/app_spacing.dart';
import 'analyze_screen.dart';
import 'session_screen.dart';
import 'settings_screen.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  void _open(BuildContext context, Widget screen) {
    wakeServer();
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => screen));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return Scaffold(
      body: CustomScrollView(
        slivers: [
          SliverAppBar.large(
            title: const Text('Pocket DRS'),
            actions: [
              IconButton(
                tooltip: 'Settings',
                onPressed: () => _open(context, const SettingsScreen()),
                icon: const Icon(Icons.settings_outlined),
              ),
            ],
          ),
          SliverPadding(
            // 16 on the sides, the same inset as the large title above
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.lg,
              0,
              AppSpacing.lg,
              AppSpacing.xxl,
            ),
            sliver: SliverList(
              delegate: SliverChildListDelegate([
                Text(
                  'Check leg before wicket calls from your phone.',
                  style: theme.textTheme.bodyLarge?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
                ),
                const SizedBox(height: AppSpacing.xl),
                _ActionCard(
                  filled: true,
                  icon: Icons.videocam_outlined,
                  title: 'Start a session',
                  description:
                      'Phone on a tripod behind the bowler. Mark the stumps '
                      'once, then tap Ball after each delivery.',
                  onTap: () => _open(context, const SessionScreen()),
                ),
                const SizedBox(height: AppSpacing.lg),
                _ActionCard(
                  filled: false,
                  icon: Icons.video_library_outlined,
                  title: 'Analyse a video',
                  description: 'Check one clip you already have.',
                  onTap: () => _open(context, const AnalyzeScreen()),
                ),
                const SizedBox(height: AppSpacing.xxl),
                Text(
                  'For a good read',
                  style: theme.textTheme.titleSmall?.copyWith(
                    color: scheme.primary,
                  ),
                ),
                const SizedBox(height: AppSpacing.sm),
                const _TipRow(
                  icon: Icons.videocam_outlined,
                  text: "Tripod behind the bowler's stumps",
                ),
                const _TipRow(
                  icon: Icons.crop_free,
                  text: 'Both sets of stumps in the frame',
                ),
                const _TipRow(
                  icon: Icons.sports_cricket,
                  text: 'A red or pink ball',
                ),
                const _TipRow(
                  icon: Icons.wb_sunny_outlined,
                  text: 'Good daylight',
                ),
                const _TipRow(
                  icon: Icons.straighten,
                  text: 'Shorter pitch? Set its length in Settings',
                ),
              ]),
            ),
          ),
        ],
      ),
    );
  }
}

class _ActionCard extends StatelessWidget {
  const _ActionCard({
    required this.filled,
    required this.icon,
    required this.title,
    required this.description,
    required this.onTap,
  });

  final bool filled;
  final IconData icon;
  final String title;
  final String description;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final fg = filled ? scheme.onPrimaryContainer : scheme.onSurface;
    final content = InkWell(
      borderRadius: BorderRadius.circular(AppRadius.md),
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: fg, size: 32),
            const SizedBox(width: AppSpacing.lg),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: theme.textTheme.titleLarge?.copyWith(color: fg),
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    description,
                    style: theme.textTheme.bodyMedium?.copyWith(
                      color: filled ? fg : scheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
    return filled
        ? Card.filled(
            margin: EdgeInsets.zero,
            color: scheme.primaryContainer,
            child: content,
          )
        : Card.outlined(margin: EdgeInsets.zero, child: content);
  }
}

class _TipRow extends StatelessWidget {
  const _TipRow({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
      child: Row(
        children: [
          Icon(icon, size: 20, color: scheme.onSurfaceVariant),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              text,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: scheme.onSurfaceVariant,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
