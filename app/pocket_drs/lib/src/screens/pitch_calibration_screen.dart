import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../analysis/calibration_config.dart';
import '../analysis/pitch_calibration.dart';
import '../analysis/video_frame_provider.dart';
import '../utils/analysis_logger.dart';
import '../utils/route_interactive.dart';

class PitchCalibrationScreen extends StatefulWidget {
  const PitchCalibrationScreen({
    super.key,
    required this.videoPath,
    required this.frameTimeMs,
    required this.config,
  });

  final String videoPath;
  final int frameTimeMs;
  final CalibrationConfig config;

  @override
  State<PitchCalibrationScreen> createState() => _PitchCalibrationScreenState();
}

class _PitchCalibrationScreenState extends State<PitchCalibrationScreen> {
  late final VideoFrameProvider _provider;

  ui.Image? _image;
  String? _error;
  bool _loading = true;
  bool _saving = false;

  int _frameMs = 0;

  final _taps = <Offset>[];

  @override
  void initState() {
    super.initState();
    _provider = VideoFrameProvider(videoPath: widget.videoPath);
    _frameMs = widget.frameTimeMs;
    _load();
  }

  @override
  void dispose() {
    _image?.dispose();
    _provider.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      // Frame decoding is best-effort and cross-platform.
      // We use a safe scrub range (0..5s) which works well for short calibration clips.
      _frameMs = _frameMs.clamp(0, 5000);

      final jpeg = await _provider.getFrameJpeg(timeMs: _frameMs, quality: 90);
      final image = await _decodeUiImage(jpeg);
      if (!mounted) return;
      setState(() {
        _image?.dispose();
        _image = image;
        _loading = false;
      });
    } catch (e) {
      await AnalysisLogger.instance.log('pitch calibration frame decode error: $e');
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _loadFrameAt(int timeMs) async {
    if (!mounted) return;
    setState(() {
      _frameMs = timeMs;
    });
    await _load();
  }

  void _reset() {
    setState(() {
      _taps.clear();
      _error = null;
    });
  }

  Future<void> _save() async {
    if (_saving) return;
    if (_taps.length != 4) return;

    setState(() {
      _saving = true;
      _error = null;
    });

    try {
      final calibration = PitchCalibration(imagePoints: List<Offset>.unmodifiable(_taps));
      calibration.validateImageQuad();

      final next = widget.config.copyWith(pitchCalibration: calibration);

      if (!mounted) return;
      // Avoid Navigator assertions if the user somehow hits Save during a transition.
      await waitForRouteInteractive(context);
      if (!mounted) return;
      Navigator.of(context).pop(next);
    } catch (e) {
      if (!mounted) return;
      String msg = e.toString().replaceAll(RegExp(r'^\\w+Error: '), '');
      msg = msg.replaceAll('StateError: ', '');
      setState(() => _error = msg);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  String _instruction() {
    if (_taps.isEmpty) {
      return 'Tap 1/4: striker end LEFT corner of the pitch rectangle';
    }
    if (_taps.length == 1) {
      return 'Tap 2/4: striker end RIGHT corner of the pitch rectangle';
    }
    if (_taps.length == 2) {
      return 'Tap 3/4: bowler end RIGHT corner of the pitch rectangle';
    }
    if (_taps.length == 3) {
      return 'Tap 4/4: bowler end LEFT corner of the pitch rectangle';
    }
    return 'Done. Save calibration to continue.';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    const durationMs = 5000;
    final frameMs = _frameMs.clamp(0, durationMs);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Pitch calibration'),
        actions: [
          IconButton(
            tooltip: 'Reset points',
            onPressed: _taps.isEmpty ? null : _reset,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text('Calibration error', style: theme.textTheme.titleLarge),
                        const SizedBox(height: 8),
                        Text(_error!),
                        const SizedBox(height: 16),
                        FilledButton(onPressed: _load, child: const Text('Try again')),
                      ],
                    ),
                  )
                : _image == null
                    ? const SizedBox.shrink()
                    : Column(
                        children: [
                          Expanded(
                            child: LayoutBuilder(
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

                                Offset toImage(Offset local) {
                                  final ix = ((local.dx - dx) / scale)
                                      .clamp(0.0, imgW - 1)
                                      .toDouble();
                                  final iy = ((local.dy - dy) / scale)
                                      .clamp(0.0, imgH - 1)
                                      .toDouble();
                                  return Offset(ix, iy);
                                }

                                return GestureDetector(
                                  behavior: HitTestBehavior.opaque,
                                  onTapUp: _taps.length >= 4
                                      ? null
                                      : (details) {
                                          final p = toImage(details.localPosition);
                                          setState(() => _taps.add(p));
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
                                      Positioned.fill(
                                        child: IgnorePointer(
                                          child: CustomPaint(
                                            painter: _TapOverlayPainter(
                                              taps: _taps,
                                              imageSize: Size(imgW, imgH),
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
                          Padding(
                            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                Text(
                                  'Frame for calibration',
                                  style: theme.textTheme.titleMedium,
                                ),
                                const SizedBox(height: 8),
                                Slider(
                                  min: 0,
                                  max: durationMs.toDouble().clamp(1.0, double.infinity),
                                  divisions: (durationMs / 200).ceil().clamp(8, 200),
                                  value: frameMs.toDouble(),
                                  label: '${(frameMs / 1000).toStringAsFixed(2)}s',
                                  onChanged: (v) {
                                    setState(() => _frameMs = v.round());
                                  },
                                  onChangeEnd: (v) => _loadFrameAt(v.round()),
                                ),
                                const SizedBox(height: 12),
                                Text(
                                  _instruction(),
                                  style: theme.textTheme.titleMedium,
                                ),
                                const SizedBox(height: 8),
                                Text(
                                  'Pitch: ${widget.config.pitchLengthM.toStringAsFixed(2)}m × ${widget.config.pitchWidthM.toStringAsFixed(2)}m',
                                  style: theme.textTheme.bodySmall?.copyWith(
                                    color: theme.colorScheme.onSurfaceVariant,
                                  ),
                                ),
                                const SizedBox(height: 12),
                                FilledButton.icon(
                                  onPressed: (_taps.length == 4 && !_saving) ? _save : null,
                                  icon: _saving
                                      ? const SizedBox(
                                          width: 18,
                                          height: 18,
                                          child: CircularProgressIndicator(strokeWidth: 2),
                                        )
                                      : const Icon(Icons.check),
                                  label: const Text('Save and continue'),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
      ),
    );
  }
}

class _TapOverlayPainter extends CustomPainter {
  _TapOverlayPainter({required this.taps, required this.imageSize});

  final List<Offset> taps;
  final Size imageSize;

  @override
  void paint(Canvas canvas, Size size) {
    if (taps.isEmpty) return;

    final sx = size.width / imageSize.width;
    final sy = size.height / imageSize.height;
    final scale = sx < sy ? sx : sy;
    final dx = (size.width - imageSize.width * scale) / 2;
    final dy = (size.height - imageSize.height * scale) / 2;

    Offset map(Offset p) => Offset(dx + p.dx * scale, dy + p.dy * scale);

    final paintDot = Paint()
      ..style = PaintingStyle.fill
      ..color = const Color(0xFFEF4444);

    final paintLine = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..color = const Color(0xFF2563EB);

    for (var i = 0; i < taps.length; i++) {
      canvas.drawCircle(map(taps[i]), 6, paintDot);
    }

    if (taps.length >= 2) {
      final path = Path()..moveTo(map(taps[0]).dx, map(taps[0]).dy);
      for (var i = 1; i < taps.length; i++) {
        final p = map(taps[i]);
        path.lineTo(p.dx, p.dy);
      }
      canvas.drawPath(path, paintLine);
    }

    if (taps.length == 4) {
      final p0 = map(taps[0]);
      final p3 = map(taps[3]);
      canvas.drawLine(p0, p3, paintLine);
    }
  }

  @override
  bool shouldRepaint(covariant _TapOverlayPainter oldDelegate) {
    return oldDelegate.taps.length != taps.length;
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
