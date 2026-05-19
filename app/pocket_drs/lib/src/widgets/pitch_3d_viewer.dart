import 'package:flutter/material.dart';
import 'dart:async';
import 'dart:convert';
import 'package:webview_flutter/webview_flutter.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../utils/app_logger.dart';
import '../analysis/pitch_pose.dart';

class Pitch3DViewer extends StatefulWidget {
  const Pitch3DViewer({
    super.key,
    this.trajectoryPoints,
    this.showAnimation = false,
    this.bounceIndex,
    this.impactIndex,
    this.decision,
    this.pose,
  });

  final List<Map<String, double>>? trajectoryPoints;
  final bool showAnimation;
  final int? bounceIndex;
  final int? impactIndex;

  /// One of: out | not_out | umpires_call
  final String? decision;
  final PitchPose? pose;

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
      // Disable WebView debug logging to reduce native log spam.
      ..setOnConsoleMessage((message) {
        // Silently ignore console messages from WebView to reduce spam.
      })
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
        AppLogger.instance.log('[3D] error: ${msg ?? 'unknown'}', level: 'ERROR');
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
      const maxAttempts = 15; // Reduced from 25 to ~2s max
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

        await Future.delayed(const Duration(milliseconds: 150));
      }
    } finally {
      _pollingReady = false;
    }
    // Polling exhausted without JS signalling ready. A 3D viewer whose JS
    // never initialised is unusable regardless of payload state, so surface
    // the error unconditionally (the payload-presence check previously here
    // could leave the viewer stuck on a blank screen with no feedback).
    if (mounted && !_jsReady && _loadError == null) {
      setState(() => _loadError = 'Failed to initialize 3D viewer');
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
      _pendingPayload = <String, Object?>{
        'points': const <Object?>[],
        if (widget.pose != null) 'pose': widget.pose!.toJson(),
      };
      _flushPayloadIfReady();
      return;
    }

    // Coerce every coordinate to a finite double. A NaN or Infinity (which
    // are valid `num` values and so survive the `?? 0.0` fallback) would make
    // jsonEncode throw, and a huge-but-finite value would collapse the 3D
    // scene; both are reduced to 0.0 here.
    double finite(Object? v) {
      final d = (v is num) ? v.toDouble() : 0.0;
      return d.isFinite ? d : 0.0;
    }

    final safePoints = pts
        .map(
          (p) => <String, num>{
            'x': finite(p['x']),
            'y': finite(p['y']),
            'z': finite(p['z']),
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
      if (widget.pose != null) 'pose': widget.pose!.toJson(),
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
        widget.showAnimation != oldWidget.showAnimation ||
        widget.pose != oldWidget.pose) {
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
            color: AppColors.inkBlack,
            padding: const EdgeInsets.all(AppSpacing.xl),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 400),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.md,
                        vertical: AppSpacing.sm,
                      ),
                      decoration: BoxDecoration(
                        color: AppColors.signalRed,
                      ),
                      child: const Text(
                        'PITCH 3D / ERROR',
                        style: TextStyle(
                          color: AppColors.inkBlack,
                          fontSize: 10,
                          fontWeight: FontWeight.w800,
                          letterSpacing: 1.6,
                        ),
                      ),
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    Text(
                      'Failed to load 3D view',
                      style: theme.textTheme.titleLarge?.copyWith(color: AppColors.bone),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    Text(
                      _loadError!,
                      style: theme.textTheme.bodySmall?.copyWith(color: AppColors.ash),
                      textAlign: TextAlign.center,
                      maxLines: 4,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: AppSpacing.xl),
                    OutlinedButton.icon(
                      onPressed: _reload,
                      icon: const Icon(Icons.refresh, size: 16, color: AppColors.bone),
                      label: const Text(
                        'RELOAD',
                        style: TextStyle(
                          color: AppColors.bone,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 1.4,
                        ),
                      ),
                      style: OutlinedButton.styleFrom(
                        side: const BorderSide(color: AppColors.bone),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          )
        else if (!_pageLoaded)
          Container(
            color: AppColors.inkBlack,
            child: Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const SizedBox(
                    width: 28,
                    height: 28,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      valueColor: AlwaysStoppedAnimation(AppColors.signalRed),
                    ),
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  Text(
                    'BOOTING PITCH 3D',
                    style: theme.textTheme.labelMedium?.copyWith(color: AppColors.ash),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}
