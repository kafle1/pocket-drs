import 'package:flutter/material.dart';
import 'dart:async';
import 'dart:convert';
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
  bool _pageLoaded = false;
  bool _jsReady = false;
  bool _pollingReady = false;

  String? _loadError;
  Map<String, Object?>? _pendingPayload;

  @override
  void initState() {
    super.initState();
    _initializeController();
    // Ensure the first render gets data without relying on didUpdateWidget.
    // We queue immediately; delivery to JS is gated on pageLoaded/jsReady.
    _queuePayload();
  }

  void _initializeController() {
    _controller = WebViewController()
      ..setBackgroundColor(Colors.transparent)
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..addJavaScriptChannel(
        'HawkEyeBridge',
        onMessageReceived: (message) {
          _handleBridgeMessage(message.message);
        },
      )
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageFinished: (String url) {
            if (!mounted) return;
            setState(() {
              _pageLoaded = true;
              _loadError = null;
            });
            _pollUntilJsReady();
            _flushPayloadIfReady();
          },
          onWebResourceError: (error) {
            if (!mounted) return;
            setState(() {
              _loadError = error.description;
            });
          },
        ),
      )
      ..loadFlutterAsset('assets/hawkeye/index.html');
  }

  void _handleBridgeMessage(String raw) {
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return;
      final type = decoded['type'];
      if (type == 'ready') {
        if (!mounted) return;
        setState(() {
          _jsReady = true;
          _loadError = null;
        });
        _flushPayloadIfReady();
        return;
      }
      if (type == 'error') {
        final msg = decoded['message'];
        if (!mounted) return;
        setState(() {
          _loadError = msg is String && msg.trim().isNotEmpty ? msg : '3D renderer error';
        });
      }
    } catch (_) {
      // Ignore malformed messages.
    }
  }

  Future<void> _pollUntilJsReady() async {
    if (_pollingReady || _jsReady == true) return;
    _pollingReady = true;
    try {
      const maxAttempts = 25; // ~3s
      for (var i = 0; i < maxAttempts; i++) {
        if (!mounted) return;
        if (_jsReady) return;

        try {
          final res = await _controller.runJavaScriptReturningResult(
            '!!(window.hawkeye && window.hawkeye.isReady)',
          );
          final ok = res == true || res == 'true' || res == 1 || res == '1';
          if (ok) {
            if (!mounted) return;
            setState(() => _jsReady = true);
            _flushPayloadIfReady();
            return;
          }
        } catch (_) {
          // Keep polling.
        }

        await Future.delayed(const Duration(milliseconds: 120));
      }
    } finally {
      _pollingReady = false;
    }
  }

  void _flushPayloadIfReady() {
    if (!_pageLoaded || !_jsReady) return;
    final payload = _pendingPayload;
    if (payload == null) return;
    _pendingPayload = null;

    try {
      _controller.runJavaScript(
        'if (window.hawkeye && window.hawkeye.updateTrajectory) window.hawkeye.updateTrajectory(${jsonEncode(payload)});',
      );
    } catch (_) {
      // Surface the issue instead of silently swallowing it.
      if (mounted) setState(() => _loadError = 'Unable to render 3D view');
    }
  }

  void _queuePayload() {
    final pts = widget.trajectoryPoints;
    if (pts == null || pts.isEmpty) {
      _pendingPayload = <String, Object?>{'points': const <Object?>[]};
      _flushPayloadIfReady();
      return;
    }

    final safePoints = pts
        .map(
          (p) => <String, num>{
            'x': (p['x'] ?? 0.0),
            'y': (p['y'] ?? 0.0),
            'z': (p['z'] ?? 0.0),
          },
        )
        .toList(growable: false);

    int clampIndex(int? value, {required int fallback}) {
      final raw = value ?? fallback;
      if (raw < 0) return 0;
      if (raw >= safePoints.length) return safePoints.length - 1;
      return raw;
    }

    _pendingPayload = <String, Object?>{
      'points': safePoints,
      'bounceIndex': clampIndex(widget.bounceIndex, fallback: 0),
      'impactIndex': clampIndex(widget.impactIndex, fallback: safePoints.length - 1),
      'decision': widget.decision,
      'animate': widget.showAnimation,
    };

    _flushPayloadIfReady();
  }

  void _sendTrajectoryData() => _queuePayload();

  @override
  void didUpdateWidget(Pitch3DViewer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.trajectoryPoints != oldWidget.trajectoryPoints ||
        widget.bounceIndex != oldWidget.bounceIndex ||
        widget.impactIndex != oldWidget.impactIndex ||
        widget.decision != oldWidget.decision ||
        widget.showAnimation != oldWidget.showAnimation) {
      _sendTrajectoryData();
    }
  }

  void _reload() {
    setState(() {
      _pageLoaded = false;
      _jsReady = false;
      _pollingReady = false;
      _loadError = null;
    });
    _controller.loadFlutterAsset('assets/hawkeye/index.html');
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Stack(
      children: [
        WebViewWidget(controller: _controller),
        if (_loadError != null)
          Container(
            color: theme.colorScheme.surface,
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.threed_rotation_outlined, size: 44, color: theme.colorScheme.onSurfaceVariant),
                    const SizedBox(height: AppSpacing.md),
                    Text('3D view failed to load', style: theme.textTheme.titleMedium, textAlign: TextAlign.center),
                    const SizedBox(height: AppSpacing.sm),
                    Text(
                      _loadError!,
                      style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                      textAlign: TextAlign.center,
                      maxLines: 4,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    FilledButton.icon(
                      onPressed: _reload,
                      icon: const Icon(Icons.refresh),
                      label: const Text('Reload 3D'),
                    ),
                  ],
                ),
              ),
            ),
          )
        else if (!_pageLoaded)
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
