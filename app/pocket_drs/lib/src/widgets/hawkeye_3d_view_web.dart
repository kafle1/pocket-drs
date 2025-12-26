import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;
import 'dart:ui_web' as ui;

import '../analysis/trajectory_3d.dart';

/// 3D Hawk-Eye visualization for Flutter Web.
///
/// We render the same offline-friendly HTML/JS into an <iframe> and push updates
/// via postMessage.
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
  final String decision;

  @override
  State<Hawkeye3DView> createState() => _Hawkeye3DViewState();
}

class _Hawkeye3DViewState extends State<Hawkeye3DView> {
  late final String _viewType;
  html.IFrameElement? _iframe;
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    _viewType = 'hawkeye-iframe-${DateTime.now().microsecondsSinceEpoch}-${identityHashCode(this)}';
    _initIFrame();
  }

  Future<void> _initIFrame() async {
    final baseHtml = await rootBundle.loadString('assets/hawkeye/index.html');
    final js = await rootBundle.loadString('assets/hawkeye/hawkeye.js');

    // Inline JS and add a postMessage listener.
    final bridge = '''
<script>
  (function(){
    function tryApply(data){
      try {
        if (window.hawkeye && window.hawkeye.updateTrajectory) {
          window.hawkeye.updateTrajectory(data);
          return true;
        }
      } catch (e) {}
      return false;
    }

    window.addEventListener('message', function(ev){
      var msg = ev && ev.data;
      if (!msg || msg.type !== 'hawkeye:update') return;
      tryApply(msg.payload);
    });

    window.addEventListener('DOMContentLoaded', function(){
      // Tell Flutter we're ready.
      try { parent.postMessage({ type: 'hawkeye:ready' }, '*'); } catch (e) {}
    });
  })();
</script>
''';

    final htmlWithInlineJs = baseHtml
        .replaceFirst('<script src="hawkeye.js"></script>', '<script>$js</script>')
        .replaceFirst('</body>', '$bridge</body>');

    final iframe = html.IFrameElement()
      ..style.border = '0'
      ..style.width = '100%'
      ..style.height = '100%'
      ..srcdoc = htmlWithInlineJs;

    _iframe = iframe;

    // Register the view factory exactly once for this instance.
    // ignore: undefined_prefixed_name
    ui.platformViewRegistry.registerViewFactory(_viewType, (int _) => iframe);

    // Listen for the ready message.
    html.window.onMessage.listen((event) {
      final data = event.data;
      if (data is Map && data['type'] == 'hawkeye:ready') {
        if (mounted) setState(() => _ready = true);
        _sendTrajectory();
      }
    });

    // Also attempt sending after a short delay (covers message ordering weirdness).
    await Future<void>.delayed(const Duration(milliseconds: 200));
    if (mounted) {
      setState(() => _ready = true);
    }
    _sendTrajectory();
  }

  Map<String, Object?> _payload() {
    final points = widget.trajectory
        .map(
          (p) => <String, Object?>{
            'x': p.x,
            'y': p.y,
            'z': p.z,
          },
        )
        .toList(growable: false);

    return <String, Object?>{
      'points': points,
      'bounceIndex': widget.bounceIndex,
      'impactIndex': widget.impactIndex,
      'decision': widget.decision,
    };
  }

  void _sendTrajectory() {
    final iframe = _iframe;
    if (iframe == null) return;

    final msg = jsonEncode(<String, Object?>{
      'type': 'hawkeye:update',
      'payload': _payload(),
    });

    try {
      iframe.contentWindow?.postMessage(jsonDecode(msg), '*');
    } catch (e) {
      if (kDebugMode) {
        debugPrint('Hawkeye iframe postMessage failed: $e');
      }
    }
  }

  @override
  void didUpdateWidget(Hawkeye3DView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (_ready) _sendTrajectory();
  }

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(16),
      child: _iframe == null
          ? const Center(child: CircularProgressIndicator(strokeWidth: 2))
          : HtmlElementView(viewType: _viewType),
    );
  }
}
