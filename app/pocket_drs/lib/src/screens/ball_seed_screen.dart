import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../analysis/video_frame_provider.dart';

class BallSeedScreen extends StatefulWidget {
  const BallSeedScreen({
    super.key,
    required this.videoPath,
    required this.timeMs,
  });

  final String videoPath;
  final int timeMs;

  @override
  State<BallSeedScreen> createState() => _BallSeedScreenState();
}

class _BallSeedScreenState extends State<BallSeedScreen> {
  ui.Image? _image;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final provider = VideoFrameProvider(videoPath: widget.videoPath);
      final jpeg = await provider.getFrameJpeg(timeMs: widget.timeMs, quality: 90);
      final image = await _decodeUiImage(jpeg);
      if (!mounted) return;
      setState(() {
        _image = image;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
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
                        onTapDown: (details) {
                          final p = details.localPosition;
                          final ix = ((p.dx - dx) / scale).clamp(0.0, imgW - 1).toDouble();
                          final iy = ((p.dy - dy) / scale).clamp(0.0, imgH - 1).toDouble();
                          Navigator.of(context).pop(Offset(ix, iy));
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
                                  child: Text(
                                    'Tap on the ball in this frame. This improves tracking across different ball types.',
                                    style: theme.textTheme.bodyMedium,
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
}

double _containScale(double w, double h, double boxW, double boxH) {
  final sx = boxW / w;
  final sy = boxH / h;
  return sx < sy ? sx : sy;
}

Future<ui.Image> _decodeUiImage(Uint8List bytes) async {
  final codec = await ui.instantiateImageCodec(bytes);
  final frame = await codec.getNextFrame();
  return frame.image;
}
