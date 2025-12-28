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
  });

  final String imagePath;
  final void Function(List<Offset>) onComplete;
  final int maxMarkers;
  final String title;
  final String subtitle;
  final List<String>? markerLabels;

  @override
  State<ImageMarker> createState() => _ImageMarkerState();
}

class _ImageMarkerState extends State<ImageMarker> {
  final List<Offset> _markers = [];
  Size? _imageSize;
  Rect? _imageRect;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
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

  Rect _computeImageRect(Size container) {
    if (_imageSize == null) return Rect.zero;
    final imgAspect = _imageSize!.width / _imageSize!.height;
    final boxAspect = container.width / container.height;
    double w, h;
    if (imgAspect > boxAspect) {
      w = container.width;
      h = w / imgAspect;
    } else {
      h = container.height;
      w = h * imgAspect;
    }
    return Rect.fromCenter(
      center: Offset(container.width / 2, container.height / 2),
      width: w,
      height: h,
    );
  }

  void _onTap(TapDownDetails d, Size container) {
    if (_markers.length >= widget.maxMarkers || _imageSize == null) return;
    final rect = _computeImageRect(container);
    final pos = d.localPosition;
    if (!rect.contains(pos)) return;
    final nx = (pos.dx - rect.left) / rect.width;
    final ny = (pos.dy - rect.top) / rect.height;
    setState(() => _markers.add(Offset(nx.clamp(0, 1), ny.clamp(0, 1))));
  }

  void _undo() {
    if (_markers.isNotEmpty) setState(() => _markers.removeLast());
  }

  void _reset() {
    if (_markers.isNotEmpty) setState(() => _markers.clear());
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
                      done ? 'All points marked' : 'Next: $nextLabel',
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
                    final container = Size(box.maxWidth, box.maxHeight);
                    _imageRect = _computeImageRect(container);
                    return GestureDetector(
                      onTapDown: (d) => _onTap(d, container),
                      behavior: HitTestBehavior.opaque,
                      child: Container(
                        color: const Color(0xFF0A0A0A),
                        child: Stack(
                          children: [
                            Center(
                              child: Image.file(
                                File(widget.imagePath),
                                fit: BoxFit.contain,
                              ),
                            ),
                            if (_imageRect != null)
                              Positioned.fromRect(
                                rect: _imageRect!,
                                child: CustomPaint(
                                  painter: _MarkerPainter(
                                    markers: _markers,
                                    color: theme.colorScheme.primary,
                                    labels: labels,
                                  ),
                                ),
                              ),
                          ],
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
            child: Row(
              children: [
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
  _MarkerPainter({required this.markers, required this.color, required this.labels});
  final List<Offset> markers;
  final Color color;
  final List<String> labels;

  @override
  void paint(Canvas canvas, Size size) {
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
  bool shouldRepaint(_MarkerPainter old) => markers.length != old.markers.length;
}
