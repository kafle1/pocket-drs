import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import 'drs_button.dart';

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
    this.showHeader = true,
  });

  final String imagePath;
  final void Function(List<Offset>) onComplete;
  final int maxMarkers;
  final String title;
  final String subtitle;
  final List<String>? markerLabels;

  /// Optional initial markers (normalized [0..1]).
  final List<Offset>? initialMarkers;

  /// Optional guide polylines (normalized).
  final List<List<Offset>>? guides;

  /// If set, guide at this index will be emphasised.
  final int? highlightGuideIndex;

  /// Show built-in header. Hidden when the host screen provides its own.
  final bool showHeader;

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
      final capped = initial
          .take(widget.maxMarkers)
          .map((p) {
            return Offset(p.dx.clamp(0.0, 1.0), p.dy.clamp(0.0, 1.0));
          })
          .toList(growable: false);
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
        _imageSize = Size(
          frame.image.width.toDouble(),
          frame.image.height.toDouble(),
        );
        _loading = false;
      });
    }
    frame.image.dispose();
  }

  void _fitToView(Size viewport) {
    if (_imageSize == null) return;
    final iw = _imageSize!.width;
    final ih = _imageSize!.height;
    if (iw <= 0 || ih <= 0 || viewport.width <= 0 || viewport.height <= 0) {
      return;
    }

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

  @override
  void dispose() {
    _transform.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final done = _markers.length == widget.maxMarkers;
    final labels =
        widget.markerLabels ??
        List.generate(widget.maxMarkers, (i) => '${i + 1}');
    final nextLabel = _markers.length < labels.length
        ? labels[_markers.length]
        : '';

    return Column(
      children: [
        if (widget.showHeader)
          Container(
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.xl,
              AppSpacing.md,
              AppSpacing.xl,
              AppSpacing.md,
            ),
            decoration: BoxDecoration(
              color: scheme.surface,
              border: Border(
                bottom: BorderSide(color: scheme.outline, width: 1),
              ),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        widget.title.toUpperCase(),
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: scheme.onSurfaceVariant,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Text(
                        done ? 'All marks placed' : 'Next · $nextLabel',
                        style: theme.textTheme.titleMedium,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
                _Counter(current: _markers.length, total: widget.maxMarkers),
              ],
            ),
          ),
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
                      color: AppColors.inkBlack,
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
                                    highlightGuideIndex:
                                        widget.highlightGuideIndex,
                                    accent: AppColors.signalRed,
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
        Container(
          decoration: BoxDecoration(
            color: scheme.surface,
            border: Border(top: BorderSide(color: scheme.outline, width: 1)),
          ),
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.xl,
                AppSpacing.md,
                AppSpacing.xl,
                AppSpacing.md,
              ),
              child: Row(
                children: [
                  _MicroButton(
                    icon: Icons.center_focus_strong_outlined,
                    onTap: (_imageSize == null || _lastViewport == null)
                        ? null
                        : () => _fitToView(_lastViewport!),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  _MicroButton(
                    icon: Icons.undo,
                    onTap: _markers.isEmpty ? null : _undo,
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  _MicroButton(
                    icon: Icons.refresh,
                    onTap: _markers.isEmpty ? null : _reset,
                  ),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: DrsButton(
                      label: 'CONTINUE',
                      icon: Icons.arrow_forward,
                      onPressed: done
                          ? () => widget.onComplete(_markers)
                          : null,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _Counter extends StatelessWidget {
  const _Counter({required this.current, required this.total});
  final int current;
  final int total;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        border: Border.all(color: theme.colorScheme.outline, width: 1),
      ),
      child: Row(
        children: [
          Text(
            current.toString().padLeft(2, '0'),
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w800,
              color: theme.colorScheme.onSurface,
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
          Text(
            ' / ${total.toString().padLeft(2, '0')}',
            style: theme.textTheme.labelMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }
}

class _MicroButton extends StatelessWidget {
  const _MicroButton({required this.icon, this.onTap});
  final IconData icon;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final disabled = onTap == null;
    return Material(
      color: Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.sm),
        side: BorderSide(color: scheme.outline, width: 1),
      ),
      child: InkWell(
        onTap: onTap,
        child: SizedBox(
          width: 44,
          height: 44,
          child: Icon(
            icon,
            size: 18,
            color: disabled ? scheme.outline : scheme.onSurface,
          ),
        ),
      ),
    );
  }
}

class _MarkerPainter extends CustomPainter {
  _MarkerPainter({
    required this.markers,
    required this.accent,
    required this.labels,
    this.guides,
    this.highlightGuideIndex,
  });
  final List<Offset> markers;
  final Color accent;
  final List<String> labels;
  final List<List<Offset>>? guides;
  final int? highlightGuideIndex;

  @override
  void paint(Canvas canvas, Size size) {
    final gs = guides;
    if (gs != null && gs.isNotEmpty) {
      for (var i = 0; i < gs.length; i++) {
        final g = gs[i];
        if (g.length < 2) continue;
        final isHighlighted =
            highlightGuideIndex != null && i == highlightGuideIndex;
        final guidePaint = Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = isHighlighted ? 2.5 : 1.5
          ..color = (isHighlighted ? AppColors.pitchGreen : AppColors.bone)
              .withValues(alpha: isHighlighted ? 0.9 : 0.4);
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

    final points = markers
        .map((m) => Offset(m.dx * size.width, m.dy * size.height))
        .toList();

    if (points.length >= 3) {
      final path = Path()..moveTo(points[0].dx, points[0].dy);
      for (var i = 1; i < points.length; i++) {
        path.lineTo(points[i].dx, points[i].dy);
      }
      if (points.length == 4) path.close();
      canvas.drawPath(path, Paint()..color = accent.withValues(alpha: 0.10));
    }

    if (points.length > 1) {
      final linePaint = Paint()
        ..color = accent
        ..strokeWidth = 1.6
        ..style = PaintingStyle.stroke;
      final path = Path()..moveTo(points[0].dx, points[0].dy);
      for (var i = 1; i < points.length; i++) {
        path.lineTo(points[i].dx, points[i].dy);
      }
      if (points.length == 4) path.close();
      canvas.drawPath(path, linePaint);
    }

    for (var i = 0; i < points.length; i++) {
      final p = points[i];
      // Crosshair
      const crossLen = 14.0;
      final crossPaint = Paint()
        ..color = accent
        ..strokeWidth = 1.4
        ..style = PaintingStyle.stroke;
      canvas.drawLine(
        Offset(p.dx - crossLen, p.dy),
        Offset(p.dx + crossLen, p.dy),
        crossPaint,
      );
      canvas.drawLine(
        Offset(p.dx, p.dy - crossLen),
        Offset(p.dx, p.dy + crossLen),
        crossPaint,
      );
      // Inner dot
      canvas.drawCircle(p, 5, Paint()..color = accent);
      canvas.drawCircle(
        p,
        5,
        Paint()
          ..color = AppColors.bone
          ..strokeWidth = 1
          ..style = PaintingStyle.stroke,
      );
      // Label tag
      final label = i < labels.length ? labels[i] : '${i + 1}';
      final tp = TextPainter(
        text: TextSpan(
          text: label.toUpperCase(),
          style: const TextStyle(
            color: AppColors.bone,
            fontSize: 9,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.2,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      final tagPad = const EdgeInsets.symmetric(horizontal: 5, vertical: 3);
      final tagRect = Rect.fromLTWH(
        p.dx + 10,
        p.dy - tp.height / 2 - tagPad.vertical / 2,
        tp.width + tagPad.horizontal,
        tp.height + tagPad.vertical,
      );
      canvas.drawRect(
        tagRect,
        Paint()..color = AppColors.inkBlack.withValues(alpha: 0.85),
      );
      canvas.drawRect(
        tagRect,
        Paint()
          ..color = accent
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1,
      );
      tp.paint(
        canvas,
        Offset(tagRect.left + tagPad.left, tagRect.top + tagPad.top),
      );
    }
  }

  @override
  bool shouldRepaint(_MarkerPainter old) {
    return markers.length != old.markers.length ||
        guides != old.guides ||
        highlightGuideIndex != old.highlightGuideIndex ||
        accent != old.accent;
  }
}
