import 'dart:async';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../analysis/video_frame_provider.dart';
import '../utils/analysis_logger.dart';
import '../utils/route_interactive.dart';

class BallSeedScreen extends StatefulWidget {
  const BallSeedScreen({
    super.key,
    required this.videoPath,
    required this.startMs,
    required this.endMs,
    required this.initialMs,
  });

  final String videoPath;
  final int startMs;
  final int endMs;
  final int initialMs;

  @override
  State<BallSeedScreen> createState() => _BallSeedScreenState();
}

class _BallSeedScreenState extends State<BallSeedScreen> {
  late final VideoFrameProvider _provider;

  ui.Image? _image;
  String? _error;
  int _timeMs = 0;
  int _loadedTimeMs = 0;
  int _loadId = 0;
  bool _popScheduled = false;
  bool _acceptingInput = true;
  bool _dragging = false;

  @override
  void initState() {
    super.initState();
    _provider = VideoFrameProvider(videoPath: widget.videoPath);
    _timeMs = widget.initialMs.clamp(widget.startMs, widget.endMs);
    _loadedTimeMs = _timeMs;
    _load(timeMs: _timeMs);
  }

  Future<void> _load({required int timeMs}) async {
    final requestId = ++_loadId;
    try {
      setState(() {
        _error = null;
        _image = null;
      });

      final jpeg = await _provider.getFrameJpeg(timeMs: timeMs, quality: 90);
      final image = await _decodeUiImage(jpeg);
      if (!mounted || requestId != _loadId) return;
      setState(() {
        _image?.dispose();
        _image = image;
        _loadedTimeMs = timeMs;
      });
    } catch (e) {
      if (!mounted || requestId != _loadId) return;
      await AnalysisLogger.instance.log('seed frame decode error at $timeMs ms: $e');
      setState(() => _error = e.toString());
    }
  }

  void _setTimeMs(int ms) {
    final clamped = ms.clamp(widget.startMs, widget.endMs);
    if (clamped == _timeMs) return;
    setState(() {
      _timeMs = clamped;
    });
  }

  Future<void> _loadCurrentTime() {
    final timeMs = _timeMs;
    return _load(timeMs: timeMs);
  }

  Future<void> _tryPopWithSeed(Offset seedPixel) async {
    // Avoid Navigator assertions when the route is still transitioning.
    if (_popScheduled || !_acceptingInput) return;
    if (!routeIsInteractive(context)) return;

    setState(() {
      _popScheduled = true;
      _acceptingInput = false;
    });

    await waitForRouteInteractive(context);
    if (!mounted) return;

    final nav = Navigator.maybeOf(context);
    if (nav == null || !nav.canPop()) return;
    nav.pop(seedPixel);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final frameIsCurrent = _image != null && _loadedTimeMs == _timeMs;
    final interactive = routeIsInteractive(context) && _acceptingInput && frameIsCurrent;

    return Scaffold(
      appBar: AppBar(title: const Text('Select the ball')),
      body: SafeArea(
        child: _error != null
            ? Padding(
                padding: const EdgeInsets.all(16),
                child: Text(_error!),
              )
            : _image == null
                ? const Center(child: CircularProgressIndicator())
                : LayoutBuilder(
                    builder: (context, constraints) {
                      final imgW = _image!.width.toDouble();
                      final imgH = _image!.height.toDouble();
                      final boxW = constraints.maxWidth;
                      final boxH = constraints.maxHeight;
                      final scale = _containScale(imgW, imgH, boxW, boxH);
                      final drawW = imgW * scale;
                      final drawH = imgH * scale;
                      final dx = (boxW - drawW) / 2;
                      final dy = (boxH - drawH) / 2;

                      return GestureDetector(
                        behavior: HitTestBehavior.opaque,
                        onTapUp: !interactive
                            ? null
                            : (details) {
                                final p = details.localPosition;
                                final ix = ((p.dx - dx) / scale).clamp(0.0, imgW - 1).toDouble();
                                final iy = ((p.dy - dy) / scale).clamp(0.0, imgH - 1).toDouble();
                                _tryPopWithSeed(Offset(ix, iy));
                              },
                        child: Stack(
                          children: [
                            Positioned.fill(
                              child: FittedBox(
                                fit: BoxFit.contain,
                                child: SizedBox(
                                  width: imgW,
                                  height: imgH,
                                  child: RawImage(image: _image),
                                ),
                              ),
                            ),
                            Positioned(
                              left: 16,
                              right: 16,
                              bottom: 16,
                              child: Card(
                                child: Padding(
                                  padding: const EdgeInsets.all(12),
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.stretch,
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Text(
                                        'Tap the ball in the frame below. If the ball is not visible yet, scrub forward a bit.',
                                        style: theme.textTheme.bodyMedium,
                                      ),
                                      const SizedBox(height: 10),
                                      Row(
                                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                        children: [
                                          Text(
                                            'Frame: ${( _timeMs / 1000.0).toStringAsFixed(2)}s',
                                            style: theme.textTheme.labelLarge,
                                          ),
                                          if (!interactive)
                                            Text(
                                              _popScheduled
                                                  ? 'Selected…'
                                                  : _dragging
                                                      ? 'Release to load'
                                                      : frameIsCurrent
                                                          ? 'Please wait…'
                                                          : 'Loading…',
                                              style: theme.textTheme.labelLarge?.copyWith(
                                                color: theme.colorScheme.onSurfaceVariant,
                                              ),
                                            ),
                                        ],
                                      ),
                                      Slider(
                                        min: widget.startMs.toDouble(),
                                        max: widget.endMs.toDouble().clamp(
                                              widget.startMs.toDouble() + 1,
                                              double.infinity,
                                            ),
                                        value: _timeMs.toDouble(),
                                        onChangeStart: !_acceptingInput
                                            ? null
                                            : (_) {
                                                setState(() => _dragging = true);
                                              },
                                        onChanged: _acceptingInput
                                            ? (v) => _setTimeMs(v.round())
                                            : null,
                                        onChangeEnd: !_acceptingInput
                                            ? null
                                            : (_) async {
                                                setState(() => _dragging = false);
                                                await _loadCurrentTime();
                                              },
                                      ),
                                      Text(
                                        'Tip: pick a frame where the ball is clearly visible (usually just after release).',
                                        style: theme.textTheme.bodySmall?.copyWith(
                                          color: theme.colorScheme.onSurfaceVariant,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
      ),
    );
  }

  @override
  void dispose() {
    _image?.dispose();
    _provider.dispose();
    super.dispose();
  }
}

double _containScale(double w, double h, double boxW, double boxH) {
  final sx = boxW / w;
  final sy = boxH / h;
  return sx < sy ? sx : sy;
}

Future<ui.Image> _decodeUiImage(Uint8List bytes) async {
  final codec = await ui.instantiateImageCodec(bytes);
  try {
    final frame = await codec.getNextFrame();
    return frame.image;
  } finally {
    codec.dispose();
  }
}
