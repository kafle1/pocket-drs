import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import '../theme/app_spacing.dart';

class Pitch3DViewer extends StatefulWidget {
  const Pitch3DViewer({
    super.key,
    this.trajectoryPoints,
    this.showAnimation = false,
    this.bounceIndex,
    this.impactIndex,
    this.decision,
  });

  final List<Map<String, double>>? trajectoryPoints;
  final bool showAnimation;
  final int? bounceIndex;
  final int? impactIndex;

  /// One of: out | not_out | umpires_call
  final String? decision;

  @override
  State<Pitch3DViewer> createState() => _Pitch3DViewerState();
}

class _Pitch3DViewerState extends State<Pitch3DViewer> {
  late final WebViewController _controller;
  bool _isReady = false;

  @override
  void initState() {
    super.initState();
    _initializeController();
  }

  void _initializeController() {
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageFinished: (String url) {
            setState(() => _isReady = true);
            _sendTrajectoryData();
          },
        ),
      )
      ..loadFlutterAsset('assets/hawkeye/index.html');
  }

  void _sendTrajectoryData() {
    if (!_isReady) return;

    final pts = widget.trajectoryPoints;
    if (pts == null || pts.isEmpty) {
      _controller.runJavaScript('window.hawkeye && window.hawkeye.updateTrajectory(null);');
      return;
    }

    final pointsJson = pts.map((p) {
      final x = p['x'];
      final y = p['y'];
      final z = p['z'];
      return '{x: ${x ?? 0}, y: ${y ?? 0}, z: ${z ?? 0}}';
    }).join(',');

    final bounce = widget.bounceIndex ?? 0;
    final impact = widget.impactIndex ?? (pts.length - 1);
    final decision = widget.decision;

    _controller.runJavaScript('''
      if (window.hawkeye && window.hawkeye.updateTrajectory) {
        window.hawkeye.updateTrajectory({
          points: [$pointsJson],
          bounceIndex: $bounce,
          impactIndex: $impact,
          decision: ${decision == null ? 'null' : "'$decision'"}
        });
      }
    ''');
  }

  @override
  void didUpdateWidget(Pitch3DViewer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.trajectoryPoints != oldWidget.trajectoryPoints ||
        widget.bounceIndex != oldWidget.bounceIndex ||
        widget.impactIndex != oldWidget.impactIndex ||
        widget.decision != oldWidget.decision) {
      _sendTrajectoryData();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        WebViewWidget(controller: _controller),
        if (!_isReady)
          Container(
            color: Colors.black,
            child: const Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  CircularProgressIndicator(color: Colors.white),
                  SizedBox(height: AppSpacing.md),
                  Text(
                    'Loading 3D View...',
                    style: TextStyle(color: Colors.white),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}
