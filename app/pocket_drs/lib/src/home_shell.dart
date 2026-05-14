import 'package:flutter/material.dart';

import 'screens/analyses_screen.dart';
import 'screens/pitches_screen.dart';
import 'screens/settings_screen.dart';
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
          content: const Text('Server unreachable'),
          action: SnackBarAction(
            label: 'Set Server URL',
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

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: IndexedStack(index: _index, children: _pages),
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          border: Border(
            top: BorderSide(
              color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3),
              width: 1,
            ),
          ),
        ),
        child: SafeArea(
          top: false,
          child: NavigationBar(
            selectedIndex: _index,
            onDestinationSelected: (i) => setState(() => _index = i),
            destinations: const [
              NavigationDestination(
                icon: Icon(Icons.sports_cricket_outlined),
                selectedIcon: Icon(Icons.sports_cricket),
                label: 'Pitches',
              ),
              NavigationDestination(
                icon: Icon(Icons.timeline_outlined),
                selectedIcon: Icon(Icons.timeline),
                label: 'Analyses',
              ),
              NavigationDestination(
                icon: Icon(Icons.settings_outlined),
                selectedIcon: Icon(Icons.settings),
                label: 'Settings',
              ),
            ],
          ),
        ),
      ),
      backgroundColor: theme.scaffoldBackgroundColor,
    );
  }
}
