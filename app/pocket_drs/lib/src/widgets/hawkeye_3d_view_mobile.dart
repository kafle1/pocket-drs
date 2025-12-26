import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../analysis/trajectory_3d.dart';

/// 3D Hawk-Eye visualization using an offline-friendly canvas renderer inside a WebView.
class Hawkeye3DView extends StatefulWidget {
  const Hawkeye3DView({
    super.key,
    required this.trajectory,
    required this.bounceIndex,
    required this.impactIndex,
    required this.decision,
  });

  final List<TrajectoryPoint3D> trajectory;
  final int bounceIndex;
  final int impactIndex;
  final String decision; // 'out', 'not_out', 'umpires_call'

  @override
  State<Hawkeye3DView> createState() => _Hawkeye3DViewState();
}

class _Hawkeye3DViewState extends State<Hawkeye3DView> {
  late final WebViewController _controller;
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    _initWebView();
  }

  Future<void> _initWebView() async {
    final html = await rootBundle.loadString('assets/hawkeye/index.html');
    final js = await rootBundle.loadString('assets/hawkeye/hawkeye.js');

    // Inline the JS into HTML.
    final fullHtml = html.replaceFirst(
      '<script src="hawkeye.js"></script>',
      '<script>$js</script>',
    );

    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFF0f172a))
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageFinished: (_) {
            setState(() => _ready = true);
            _sendTrajectory();
          },
        ),
      )
      ..loadHtmlString(fullHtml);
  }

  @override
  void didUpdateWidget(Hawkeye3DView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (_ready) {
      _sendTrajectory();
    }
  }

  void _sendTrajectory() {
    final points = widget.trajectory
        .map(
          (p) => <String, Object?>{
            'x': p.x,
            'y': p.y,
            'z': p.z,
          },
        )
        .toList(growable: false);

    final data = jsonEncode(<String, Object?>{
      'points': points,
      'bounceIndex': widget.bounceIndex,
      'impactIndex': widget.impactIndex,
      'decision': widget.decision,
    });

    _controller.runJavaScript('window.hawkeye.updateTrajectory($data);');
  }

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(16),
      child: _ready
          ? WebViewWidget(controller: _controller)
          : const Center(
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
    );
  }
}
