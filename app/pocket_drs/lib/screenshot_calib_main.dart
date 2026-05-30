// Screenshot harness: renders the real ImageMarker pitch-calibration screen
// with the test3 frame and its four corner taps pre-placed. Not shipped.
// Build:  flutter build web -t lib/screenshot_calib_main.dart
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'src/theme/app_theme.dart';
import 'src/widgets/image_marker.dart';

void main() => runApp(const CalibApp());

class CalibApp extends StatelessWidget {
  const CalibApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light(),
        home: const CalibPage(),
      );
}

class CalibPage extends StatefulWidget {
  const CalibPage({super.key});
  @override
  State<CalibPage> createState() => _CalibPageState();
}

class _CalibPageState extends State<CalibPage> {
  Uint8List? _bytes;
  String? _err;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await http.get(Uri.parse('frame0.jpg'));
      setState(() => _bytes = r.bodyBytes);
    } catch (e) {
      setState(() => _err = '$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_err != null) return Scaffold(body: Center(child: Text('ERR $_err')));
    final b = _bytes;
    if (b == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return Scaffold(
      body: ImageMarker(
        imageBytes: b,
        maxMarkers: 4,
        title: 'Mark Pitch Corners',
        subtitle: 'Tap clockwise from the striker end',
        markerLabels: const [
          'Striker Left',
          'Striker Right',
          'Bowler Right',
          'Bowler Left',
        ],
        // test3 recovered corners (normalized 0..1), matching test3_e2e.py.
        initialMarkers: const [
          Offset(0.324, 0.521),
          Offset(0.704, 0.521),
          Offset(0.787, 0.911),
          Offset(0.185, 0.911),
        ],
        onComplete: (_) {},
      ),
    );
  }
}
