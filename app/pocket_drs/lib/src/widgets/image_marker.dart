import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';

class ImageMarker extends StatefulWidget {
  const ImageMarker({
    super.key,
    required this.imagePath,
    required this.onComplete,
    this.maxMarkers = 4,
    this.title = 'Mark Points',
    this.subtitle = 'Tap to mark points on the image',
    this.markerLabels,
    this.initialMarkers,
    this.guides,
    this.highlightGuideIndex,
  });

  final String imagePath;
  final void Function(List<Offset>) onComplete;
  final int maxMarkers;
  final String title;
  final String subtitle;
  final List<String>? markerLabels;

  /// Optional initial markers (normalized [0..1]).
  ///
  /// When provided, the user can refine by undoing/retapping.
  final List<Offset>? initialMarkers;

  /// Optional guide polylines to draw behind markers.
  ///
  /// Each guide is expressed in normalized coordinates [0..1] relative to the
  /// source image.
  final List<List<Offset>>? guides;

  /// If set, the guide at this index will be emphasized.
  final int? highlightGuideIndex;

  @override
  State<ImageMarker> createState() => _ImageMarkerState();
}

class _ImageMarkerState extends State<ImageMarker> {
  final List<Offset> _markers = [];
  Size? _imageSize;
  bool _loading = true;

  final TransformationController _transform = TransformationController();
  bool _didInitTransform = false;
  Size? _lastViewport;

  @override
  void initState() {
    super.initState();
    final initial = widget.initialMarkers;
    if (initial != null && initial.isNotEmpty) {
      final capped = initial.take(widget.maxMarkers).map((p) {
        return Offset(p.dx.clamp(0.0, 1.0), p.dy.clamp(0.0, 1.0));
      }).toList(growable: false);
      _markers.addAll(capped);
    }
    _loadImage();
  }

  Future<void> _loadImage() async {
    final file = File(widget.imagePath);
    final bytes = await file.readAsBytes();
    final codec = await ui.instantiateImageCodec(bytes);
    final frame = await codec.getNextFrame();
    if (mounted) {
      setState(() {
        _imageSize = Size(frame.image.width.toDouble(), frame.image.height.toDouble());
        _loading = false;
      });
    }
    frame.image.dispose();
  }

  void _fitToView(Size viewport) {
    if (_imageSize == null) return;
    final iw = _imageSize!.width;
    final ih = _imageSize!.height;
    if (iw <= 0 || ih <= 0 || viewport.width <= 0 || viewport.height <= 0) return;

    final s = (viewport.width / iw).clamp(0.05, 10.0);
    final s2 = (viewport.height / ih).clamp(0.05, 10.0);
    final scale = s < s2 ? s : s2;

    final dx = (viewport.width - iw * scale) / 2.0;
    final dy = (viewport.height - ih * scale) / 2.0;

    _transform.value = Matrix4.identity()
      ..translate(dx, dy)
      ..scale(scale);
  }

  void _onTapUp(TapUpDetails d, Size viewport) {
    if (_markers.length >= widget.maxMarkers || _imageSize == null) return;

    // Convert viewport coords -> scene coords (image pixel space).
    final scene = _transform.toScene(d.localPosition);
    final iw = _imageSize!.width;
    final ih = _imageSize!.height;

    if (scene.dx < 0 || scene.dy < 0 || scene.dx > iw || scene.dy > ih) return;

    final nx = (scene.dx / iw).clamp(0.0, 1.0);
    final ny = (scene.dy / ih).clamp(0.0, 1.0);
    setState(() => _markers.add(Offset(nx, ny)));
  }

  void _undo() {
    if (_markers.isNotEmpty) setState(() => _markers.removeLast());
  }

  void _reset() {
    if (_markers.isNotEmpty) setState(() => _markers.clear());
  }

  void _resetView(Size viewport) {
    _fitToView(viewport);
  }

  @override
  void dispose() {
    _transform.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final done = _markers.length == widget.maxMarkers;
    final labels = widget.markerLabels ?? List.generate(widget.maxMarkers, (i) => '${i + 1}');
    final nextLabel = _markers.length < labels.length ? labels[_markers.length] : '';

    return Column(
      children: [
        // Compact header
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
          decoration: BoxDecoration(
            gradient: LinearGradient(
              colors: [
                theme.colorScheme.surface,
                theme.colorScheme.surface.withValues(alpha: 0.95),
              ],
            ),
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      widget.title,
                      style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      widget.subtitle,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      done ? 'All points marked' : 'Next: $nextLabel · Pinch to zoom for precision',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              _ProgressRing(current: _markers.length, total: widget.maxMarkers),
            ],
          ),
        ),
        // Image canvas
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : LayoutBuilder(
                  builder: (context, box) {
                    final viewport = Size(box.maxWidth, box.maxHeight);
                    _lastViewport = viewport;
                    if (!_didInitTransform) {
                      _didInitTransform = true;
                      WidgetsBinding.instance.addPostFrameCallback((_) {
                        if (!mounted) return;
                        _fitToView(viewport);
                      });
                    }

                    final imgSize = _imageSize;
                    if (imgSize == null) return const SizedBox();

                    return Container(
                      color: const Color(0xFF0A0A0A),
                      child: GestureDetector(
                        onTapUp: (d) => _onTapUp(d, viewport),
                        behavior: HitTestBehavior.opaque,
                        child: InteractiveViewer(
                          transformationController: _transform,
                          minScale: 0.5,
                          maxScale: 12.0,
                          boundaryMargin: const EdgeInsets.all(48),
                          constrained: false,
                          child: SizedBox(
                            width: imgSize.width,
                            height: imgSize.height,
                            child: Stack(
                              fit: StackFit.expand,
                              children: [
                                Image.file(
                                  File(widget.imagePath),
                                  fit: BoxFit.fill,
                                ),
                                CustomPaint(
                                  painter: _MarkerPainter(
                                    markers: _markers,
                                    guides: widget.guides,
                                    highlightGuideIndex: widget.highlightGuideIndex,
                                    color: theme.colorScheme.primary,
                                    labels: labels,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    );
                  },
                ),
        ),
        // Action bar
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: theme.colorScheme.surface,
            border: Border(top: BorderSide(color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3))),
          ),
          child: SafeArea(
            top: false,
            child: LayoutBuilder(
              builder: (context, box) {
                return Row(
                  children: [
                    _ActionButton(
                      icon: Icons.center_focus_strong_rounded,
                      label: 'Fit',
                      onTap: (_imageSize == null || _lastViewport == null)
                          ? null
                          : () => _resetView(_lastViewport!),
                    ),
                    const SizedBox(width: 8),
                    _ActionButton(
                      icon: Icons.undo_rounded,
                      label: 'Undo',
                      onTap: _markers.isEmpty ? null : _undo,
                    ),
                    const SizedBox(width: 8),
                    _ActionButton(
                      icon: Icons.refresh_rounded,
                      label: 'Reset',
                      onTap: _markers.isEmpty ? null : _reset,
                    ),
                    const Spacer(),
                    FilledButton(
                      onPressed: done ? () => widget.onComplete(_markers) : null,
                      style: FilledButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                      ),
                      child: const Text('Continue'),
                    ),
                  ],
                );
              },
            ),
          ),
        ),
      ],
    );
  }
}

class _ProgressRing extends StatelessWidget {
  const _ProgressRing({required this.current, required this.total});
  final int current;
  final int total;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final progress = current / total;
    return SizedBox(
      width: 48,
      height: 48,
      child: Stack(
        alignment: Alignment.center,
        children: [
          CircularProgressIndicator(
            value: progress,
            strokeWidth: 3,
            backgroundColor: theme.colorScheme.outlineVariant.withValues(alpha: 0.3),
            color: theme.colorScheme.primary,
          ),
          Text(
            '$current/$total',
            style: theme.textTheme.labelSmall?.copyWith(fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({required this.icon, required this.label, this.onTap});
  final IconData icon;
  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final enabled = onTap != null;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          child: Row(
            children: [
              Icon(icon, size: 18, color: enabled ? theme.colorScheme.onSurface : theme.colorScheme.outline),
              const SizedBox(width: 6),
              Text(
                label,
                style: theme.textTheme.labelMedium?.copyWith(
                  color: enabled ? theme.colorScheme.onSurface : theme.colorScheme.outline,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MarkerPainter extends CustomPainter {
  _MarkerPainter({
    required this.markers,
    required this.color,
    required this.labels,
    this.guides,
    this.highlightGuideIndex,
  });
  final List<Offset> markers;
  final Color color;
  final List<String> labels;

  final List<List<Offset>>? guides;
  final int? highlightGuideIndex;

  @override
  void paint(Canvas canvas, Size size) {
    // Guides first.
    final gs = guides;
    if (gs != null && gs.isNotEmpty) {
      for (var i = 0; i < gs.length; i++) {
        final g = gs[i];
        if (g.length < 2) continue;
        final isHighlighted = highlightGuideIndex != null && i == highlightGuideIndex;
        final guidePaint = Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = isHighlighted ? 3.0 : 2.0
          ..color = (isHighlighted ? const Color(0xFF38BDF8) : const Color(0xFFFFFFFF)).withValues(
            alpha: isHighlighted ? 0.95 : 0.55,
          );

        final path = Path();
        final p0 = Offset(g[0].dx * size.width, g[0].dy * size.height);
        path.moveTo(p0.dx, p0.dy);
        for (var j = 1; j < g.length; j++) {
          final pj = Offset(g[j].dx * size.width, g[j].dy * size.height);
          path.lineTo(pj.dx, pj.dy);
        }
        canvas.drawPath(path, guidePaint);
      }
    }

    if (markers.isEmpty) return;

    final points = markers.map((m) => Offset(m.dx * size.width, m.dy * size.height)).toList();

    // Draw filled polygon
    if (points.length >= 3) {
      final path = Path()..moveTo(points[0].dx, points[0].dy);
      for (var i = 1; i < points.length; i++) {
        path.lineTo(points[i].dx, points[i].dy);
      }
      if (points.length == 4) path.close();
      canvas.drawPath(path, Paint()..color = color.withValues(alpha: 0.15));
    }

    // Draw lines
    if (points.length > 1) {
      final linePaint = Paint()
        ..color = color
        ..strokeWidth = 2
        ..style = PaintingStyle.stroke;
      final path = Path()..moveTo(points[0].dx, points[0].dy);
      for (var i = 1; i < points.length; i++) {
        path.lineTo(points[i].dx, points[i].dy);
      }
      if (points.length == 4) path.close();
      canvas.drawPath(path, linePaint);
    }

    // Draw markers
    for (var i = 0; i < points.length; i++) {
      final p = points[i];
      // Outer ring
      canvas.drawCircle(p, 14, Paint()..color = color.withValues(alpha: 0.3));
      // Inner filled
      canvas.drawCircle(p, 10, Paint()..color = color);
      // Label
      final label = i < labels.length ? labels[i] : '${i + 1}';
      final tp = TextPainter(
        text: TextSpan(
          text: label,
          style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, p - Offset(tp.width / 2, tp.height / 2));
    }
  }

  @override
  bool shouldRepaint(_MarkerPainter old) {
    return markers.length != old.markers.length ||
        guides != old.guides ||
        highlightGuideIndex != old.highlightGuideIndex ||
        color != old.color;
  }
}
