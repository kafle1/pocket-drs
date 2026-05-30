// Screenshot harness: renders the real TrajectoryVideoView result screen with
// the test3 result + video so it can be captured for the report. Not shipped.
// Build:  flutter build web -t lib/screenshot_main.dart
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'src/api/analysis_result.dart';
import 'src/theme/app_theme.dart';
import 'src/widgets/trajectory_video_view.dart';

void main() => runApp(const ShotApp());

class ShotApp extends StatelessWidget {
  const ShotApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light(),
        home: const ShotPage(),
      );
}

class ShotPage extends StatefulWidget {
  const ShotPage({super.key});
  @override
  State<ShotPage> createState() => _ShotPageState();
}

class _ShotPageState extends State<ShotPage> {
  AnalysisResult? _result;
  String? _decision;
  String? _err;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await http.get(Uri.parse('result.json'));
      final j = jsonDecode(r.body) as Map<String, Object?>;
      final dec = ((j['lbw'] as Map?)?['decision']) as String?;
      setState(() {
        _result = AnalysisResult.fromServerJson(j);
        _decision = dec;
      });
    } catch (e) {
      setState(() => _err = '$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_err != null) {
      return Scaffold(body: Center(child: Text('ERR: $_err')));
    }
    final res = _result;
    if (res == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return Scaffold(
      backgroundColor: Colors.black,
      body: Center(
        child: TrajectoryVideoView(
          videoPath: 'test3.mp4',
          result: res,
          decision: _decision,
        ),
      ),
    );
  }
}
