import 'dart:typed_data';
import 'dart:ui' as ui;
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';

class ImageMarker extends StatefulWidget {
  const ImageMarker({
    super.key,
    required this.imageBytes,
    required this.onComplete,
    this.maxMarkers = 4,
    this.markerLabels,
    this.initialMarkers,
  });

  final Uint8List imageBytes;
  final void Function(List<Offset>) onComplete;
  final int maxMarkers;
  final List<String>? markerLabels;

  /// Optional initial markers (normalized [0..1]).
  final List<Offset>? initialMarkers;

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
  int? _dragging;
  Offset? _dragLast;

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
    final codec = await ui.instantiateImageCodec(widget.imageBytes);
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
      ..translateByDouble(dx, dy, 0, 1)
      ..scaleByDouble(scale, scale, scale, 1);
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

  // nearest mark within a fingertip of a scene point, sized in screen space so it holds at any zoom
  int? _markerAt(Offset scene) {
    final size = _imageSize;
    if (size == null) return null;
    final reach = 28 / _transform.value.getMaxScaleOnAxis();
    int? best;
    var bestD = reach;
    for (var i = 0; i < _markers.length; i++) {
      final d =
          (Offset(_markers[i].dx * size.width, _markers[i].dy * size.height) -
                  scene)
              .distance;
      if (d <= bestD) {
        best = i;
        bestD = d;
      }
    }
    return best;
  }

  void _dragStart(DragStartDetails d) {
    final i = _markerAt(d.localPosition);
    if (i == null) return;
    setState(() {
      _dragging = i;
      _dragLast = d.localPosition;
    });
  }

  // quarter speed, so a fingertip slip moves the mark by a fraction of a pixel
  void _dragUpdate(DragUpdateDetails d) {
    final i = _dragging, last = _dragLast, size = _imageSize;
    if (i == null || last == null || size == null) return;
    final delta = (d.localPosition - last) * 0.25;
    _dragLast = d.localPosition;
    final m = _markers[i];
    setState(
      () => _markers[i] = Offset(
        (m.dx + delta.dx / size.width).clamp(0.0, 1.0),
        (m.dy + delta.dy / size.height).clamp(0.0, 1.0),
      ),
    );
  }

  void _dragEnd() => setState(() {
    _dragging = null;
    _dragLast = null;
  });

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
        Container(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.md,
            AppSpacing.lg,
            AppSpacing.md,
          ),
          color: scheme.surfaceContainer,
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      done
                          ? 'All marks placed'
                          : 'Tap ${_markers.length + 1} · $nextLabel',
                      style: theme.textTheme.titleMedium,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      'Pinch to zoom, drag a mark to move it',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: scheme.onSurfaceVariant,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
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

                    final dragging = _dragging;
                    return Container(
                      color: AppColors.video,
                      child: Stack(
                        children: [
                          GestureDetector(
                            onTapUp: (d) => _onTapUp(d, viewport),
                            behavior: HitTestBehavior.opaque,
                            child: InteractiveViewer(
                              transformationController: _transform,
                              minScale: 0.5,
                              maxScale: 12.0,
                              boundaryMargin: const EdgeInsets.all(48),
                              constrained: false,
                              child: RawGestureDetector(
                                gestures: {
                                  _MarkerDrag:
                                      GestureRecognizerFactoryWithHandlers<
                                        _MarkerDrag
                                      >(
                                        () => _MarkerDrag(
                                          (p) => _markerAt(p) != null,
                                        ),
                                        (r) => r
                                          ..onStart = _dragStart
                                          ..onUpdate = _dragUpdate
                                          ..onEnd = ((_) => _dragEnd())
                                          ..onCancel = _dragEnd,
                                      ),
                                },
                                child: SizedBox(
                                  width: imgSize.width,
                                  height: imgSize.height,
                                  child: Stack(
                                    fit: StackFit.expand,
                                    children: [
                                      Image.memory(
                                        widget.imageBytes,
                                        fit: BoxFit.fill,
                                        gaplessPlayback: true,
                                      ),
                                      CustomPaint(
                                        painter: _MarkerPainter(
                                          markers: _markers,
                                          accent: AppColors.track,
                                          transform: _transform,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            ),
                          ),
                          if (dragging != null)
                            _Loupe(
                              at: MatrixUtils.transformPoint(
                                _transform.value,
                                Offset(
                                  _markers[dragging].dx * imgSize.width,
                                  _markers[dragging].dy * imgSize.height,
                                ),
                              ),
                              viewport: viewport,
                            ),
                        ],
                      ),
                    );
                  },
                ),
        ),
        Container(
          color: scheme.surfaceContainer,
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
                  IconButton.outlined(
                    icon: const Icon(Icons.fit_screen_outlined),
                    tooltip: 'Fit to screen',
                    onPressed: (_imageSize == null || _lastViewport == null)
                        ? null
                        : () => _fitToView(_lastViewport!),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  IconButton.outlined(
                    icon: const Icon(Icons.undo),
                    tooltip: 'Undo',
                    onPressed: _markers.isEmpty ? null : _undo,
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  IconButton.outlined(
                    icon: const Icon(Icons.restart_alt),
                    tooltip: 'Clear all',
                    onPressed: _markers.isEmpty ? null : _reset,
                  ),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: SizedBox(
                      width: double.infinity,
                      child: FilledButton.icon(
                        icon: const Icon(Icons.arrow_forward),
                        label: const Text('Continue'),
                        onPressed: done
                            ? () => widget.onComplete(_markers)
                            : null,
                      ),
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

/// Lets a drag start only on an existing mark, so a drag anywhere else still pans the image.
class _MarkerDrag extends PanGestureRecognizer {
  _MarkerDrag(this.onMarker);
  final bool Function(Offset scene) onMarker;

  @override
  bool isPointerAllowed(PointerEvent event) =>
      onMarker(event.localPosition) && super.isPointerAllowed(event);
}

/// Magnified view of the dragged mark, drawn above it so the finger never hides the corner.
class _Loupe extends StatelessWidget {
  const _Loupe({required this.at, required this.viewport});
  final Offset at;
  final Size viewport;

  static const _size = 128.0;

  @override
  Widget build(BuildContext context) {
    final above = at.dy - _size - 24;
    final centre = Offset(
      at.dx.clamp(_size / 2, viewport.width - _size / 2),
      above >= 0 ? above + _size / 2 : at.dy + 24 + _size / 2,
    );
    return Positioned(
      left: centre.dx - _size / 2,
      top: centre.dy - _size / 2,
      child: IgnorePointer(
        child: RawMagnifier(
          size: const Size.square(_size),
          magnificationScale: 3,
          focalPointOffset: at - centre,
          decoration: const MagnifierDecoration(
            shape: CircleBorder(
              side: BorderSide(color: AppColors.track, width: 2),
            ),
          ),
        ),
      ),
    );
  }
}

class _Counter extends StatelessWidget {
  const _Counter({required this.current, required this.total});
  final int current;
  final int total;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 250),
      transitionBuilder: (child, animation) =>
          FadeTransition(opacity: animation, child: child),
      child: Container(
        key: ValueKey(current),
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        decoration: BoxDecoration(
          color: scheme.secondaryContainer,
          borderRadius: BorderRadius.circular(AppRadius.xl),
        ),
        child: Text(
          '$current of $total',
          style: AppTheme.tabular(
            Theme.of(context).textTheme.labelLarge?.copyWith(
              color: scheme.onSecondaryContainer,
            ),
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
    required this.transform,
  }) : super(repaint: transform);
  final List<Offset> markers;
  final Color accent;
  final TransformationController transform;

  @override
  void paint(Canvas canvas, Size size) {
    // sizes are in screen points, so marks stay thin and never cover the corner when zoomed in
    final s = 1 / transform.value.getMaxScaleOnAxis();
    final points = markers
        .map((m) => Offset(m.dx * size.width, m.dy * size.height))
        .toList();

    // every 4 taps outline one quad, so the two stump sets never join up
    for (var i = 0; i < points.length; i += 4) {
      final q = points.sublist(i, (i + 4).clamp(0, points.length));
      final path = Path()..addPolygon(q, q.length == 4);
      if (q.length >= 3) {
        canvas.drawPath(path, Paint()..color = accent.withValues(alpha: 0.10));
      }
      if (q.length >= 2) {
        canvas.drawPath(
          path,
          Paint()
            ..color = accent
            ..strokeWidth = 1.6 * s
            ..style = PaintingStyle.stroke,
        );
      }
    }

    for (var i = 0; i < points.length; i++) {
      final p = points[i];
      // crosshair with an open centre, so the exact corner stays visible
      final crossPaint = Paint()
        ..color = accent
        ..strokeWidth = 1.4 * s
        ..style = PaintingStyle.stroke;
      for (final d in const [
        Offset(1, 0),
        Offset(-1, 0),
        Offset(0, 1),
        Offset(0, -1),
      ]) {
        canvas.drawLine(p + d * (4 * s), p + d * (16 * s), crossPaint);
      }
      // numbered dot off the corner, away from its quad, so dots never cover a corner or each other
      final corner = const [
        Offset(-1, -1),
        Offset(1, -1),
        Offset(1, 1),
        Offset(-1, 1),
      ][i % 4];
      final dot = p + corner * (13 * s);
      canvas.drawCircle(dot, 8 * s, Paint()..color = accent);
      final tp = TextPainter(
        text: TextSpan(
          text: '${i + 1}',
          style: TextStyle(
            color: AppColors.onVideo,
            fontSize: 10 * s,
            fontWeight: FontWeight.w700,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, dot - Offset(tp.width / 2, tp.height / 2));
    }
  }

  @override
  bool shouldRepaint(_MarkerPainter old) => true;
}

/// The 8 stump corner taps: striker (far) end then bowler (near) end, each
/// top-left, top-right, bottom-right, bottom-left.
class StumpMarker extends StatelessWidget {
  const StumpMarker({
    super.key,
    required this.frame,
    required this.onComplete,
    this.initialMarkers,
  });

  final Uint8List frame;
  final void Function(List<Offset>) onComplete;
  final List<Offset>? initialMarkers;

  void _check(BuildContext context, List<Offset> m) {
    for (final (i, end) in [(0, "batter's"), (4, "bowler's")]) {
      final [tl, tr, br, bl] = m.sublist(i, i + 4);
      if (tl.dy + tr.dy >= br.dy + bl.dy || tl.dx + bl.dx >= tr.dx + br.dx) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'For the $end stumps, tap top left, top right, bottom right, '
              'then bottom left',
            ),
          ),
        );
        return;
      }
    }
    onComplete(m);
  }

  @override
  Widget build(BuildContext context) => ImageMarker(
    imageBytes: frame,
    maxMarkers: 8,
    markerLabels: const [
      "Batter's stumps, top left",
      "Batter's stumps, top right",
      "Batter's stumps, bottom right",
      "Batter's stumps, bottom left",
      "Bowler's stumps, top left",
      "Bowler's stumps, top right",
      "Bowler's stumps, bottom right",
      "Bowler's stumps, bottom left",
    ],
    initialMarkers: initialMarkers,
    onComplete: (m) => _check(context, m),
  );
}
