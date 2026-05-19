import 'package:flutter/material.dart';

import 'screens/analyses_screen.dart';
import 'screens/pitches_screen.dart';
import 'screens/settings_screen.dart';
import 'theme/app_spacing.dart';
import 'utils/app_settings.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;

  @override
  void initState() {
    super.initState();
    _checkServerReachable();
  }

  Future<void> _checkServerReachable() async {
    final url = await AppSettings.getServerUrl();
    final reachable = await AppSettings.probeServerReachable(url);
    if (!reachable && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: const Text('SERVER UNREACHABLE'),
          action: SnackBarAction(
            label: 'CONFIGURE',
            onPressed: () => setState(() => _index = 2),
          ),
          duration: const Duration(seconds: 6),
        ),
      );
    }
  }

  static const _pages = <Widget>[
    PitchesScreen(),
    AnalysesScreen(),
    SettingsScreen(),
  ];

  void _select(int i) => setState(() => _index = i);

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      body: IndexedStack(index: _index, children: _pages),
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          border: Border(top: BorderSide(color: scheme.outline, width: 1)),
          color: scheme.surface,
        ),
        child: SafeArea(
          top: false,
          child: Row(
            children: [
              _NavTab(
                label: 'PITCHES',
                icon: Icons.grid_view_outlined,
                selected: _index == 0,
                onTap: () => _select(0),
              ),
              _NavTab(
                label: 'ANALYSES',
                icon: Icons.bar_chart_outlined,
                selected: _index == 1,
                onTap: () => _select(1),
              ),
              _NavTab(
                label: 'SETTINGS',
                icon: Icons.tune_outlined,
                selected: _index == 2,
                onTap: () => _select(2),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NavTab extends StatelessWidget {
  const _NavTab({
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final fg = selected ? scheme.onSurface : scheme.onSurfaceVariant;

    return Expanded(
      child: InkWell(
        onTap: onTap,
        child: SizedBox(
          height: 64,
          child: Stack(
            children: [
              Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(icon, size: 20, color: fg),
                    const SizedBox(height: AppSpacing.xs + 2),
                    Text(
                      label,
                      style: TextStyle(
                        color: fg,
                        fontSize: 9.5,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
              if (selected)
                Positioned(
                  top: 0,
                  left: 0,
                  right: 0,
                  child: Container(height: 2, color: scheme.onSurface),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
