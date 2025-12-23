import 'package:flutter/material.dart';

import 'screens/home_screen.dart';

class PocketDrsApp extends StatelessWidget {
  const PocketDrsApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'PocketDRS',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF0F766E)),
        useMaterial3: true,
      ),
      home: const HomeScreen(),
    );
  }
}
