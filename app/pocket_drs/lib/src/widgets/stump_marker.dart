import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart' show listEquals;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import 'pitch_setup.dart';

const _ends = ['Far stumps (batter)', 'Near stumps (bowler)'];
const _corners = ['top left', 'top right', 'bottom right', 'bottom left'];
const _cornerHelp = [
  'Top of the left stump, outside edge',
  'Top of the right stump, outside edge',
  'Foot of the right stump, outside edge',
  'Foot of the left stump, outside edge',
];

String markName(int i) => '${_ends[i ~/ 4]}, ${_corners[i % 4]}';

enum _Mode { none, place, drag, view }

/// The 8 stump corners: far (batter's) set then near (bowler's) set, each top left, top right,
/// bottom right, bottom left; one may be null when it can't be seen. One finger places or moves
/// a mark with a loupe beside it; two fingers zoom and pan.
class StumpMarker extends StatefulWidget {
  const StumpMarker({
    super.key,
    required this.frame,
    required this.onComplete,
    required this.actionLabel,
    this.initialMarks,
    this.suspect,
    this.hand,
    this.onHand,
    this.onEdited,
  });

  final Uint8List frame;
  final void Function(List<Offset?>) onComplete;
  final String actionLabel;
  final List<Offset?>? initialMarks;

  /// The batter's hand, shown and switched here when given.
  final String? hand;
  final ValueChanged<String>? onHand;

  /// The mark the server says doesn't line up with the others.
  final int? suspect;

  /// Called after each change to the marks, so the screen can ask before throwing them away.
  final VoidCallback? onEdited;

  @override
  State<StumpMarker> createState() => _StumpMarkerState();
}

class _StumpMarkerState extends State<StumpMarker> {
  late List<Offset?> _marks = [
    for (final p in (widget.initialMarks ?? const <Offset?>[]).take(8))
      p == null ? null : Offset(p.dx.clamp(0.0, 1.0), p.dy.clamp(0.0, 1.0)),
  ];
  final _undo = <List<Offset?>>[];
  late int? _suspect = widget.suspect;
  Size? _image;
  bool _failed = false;

  final _view = TransformationController();
  Size? _viewport;
  double _fitScale = 1;

  _Mode _mode = _Mode.none;
  int? _active;
  Offset? _finger;
  Offset _gestureStart = Offset.zero;
  Offset _markStart = Offset.zero;
  Matrix4 _viewStart = Matrix4.identity();
  List<Offset?> _before = const [];

  @override
  void initState() {
    super.initState();
    _decode();
  }

  Future<void> _decode() async {
    try {
      final codec = await ui.instantiateImageCodec(widget.frame);
      final frame = await codec.getNextFrame();
      final size = Size(
        frame.image.width.toDouble(),
        frame.image.height.toDouble(),
      );
      frame.image.dispose();
      if (mounted) setState(() => _image = size);
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  @override
  void dispose() {
    _view.dispose();
    super.dispose();
  }

  void _fit(Size viewport) {
    final img = _image;
    if (img == null || viewport.isEmpty) return;
    final s = math.min(
      viewport.width / img.width,
      viewport.height / img.height,
    );
    _fitScale = s;
    _view.value = Matrix4.identity()
      ..translateByDouble(
        (viewport.width - img.width * s) / 2,
        (viewport.height - img.height * s) / 2,
        0,
        1,
      )
      ..scaleByDouble(s, s, 1, 1);
  }

  double get _scale => _view.value.getMaxScaleOnAxis();

  Offset _toScreen(Offset norm) => MatrixUtils.transformPoint(
    _view.value,
    Offset(norm.dx * _image!.width, norm.dy * _image!.height),
  );

  Offset _toNorm(Offset screen) {
    final p = _view.toScene(screen);
    return Offset(
      (p.dx / _image!.width).clamp(0.0, 1.0),
      (p.dy / _image!.height).clamp(0.0, 1.0),
    );
  }

  // nearest mark within a fingertip, measured on screen so it holds at any zoom
  int? _markAt(Offset screen) {
    int? best;
    var bestD = 36.0;
    for (var i = 0; i < _marks.length; i++) {
      final m = _marks[i];
      if (m == null) continue;
      final d = (_toScreen(m) - screen).distance;
      if (d <= bestD) {
        best = i;
        bestD = d;
      }
    }
    return best;
  }

  void _start(ScaleStartDetails d) {
    _gestureStart = d.localFocalPoint;
    _viewStart = _view.value.clone();
    _before = List.of(_marks);
    if (d.pointerCount > 1) return setState(() => _mode = _Mode.view);
    final hit = _markAt(d.localFocalPoint);
    setState(() {
      _finger = d.localFocalPoint;
      if (hit != null) {
        _mode = _Mode.drag;
        _active = hit;
        _markStart = _marks[hit]!;
      } else if (_marks.length < 8) {
        _mode = _Mode.place;
        _marks.add(_toNorm(d.localFocalPoint));
        _active = _marks.length - 1;
      } else {
        _mode = _Mode.view;
      }
    });
    if (_mode != _Mode.view) HapticFeedback.selectionClick();
  }

  void _update(ScaleUpdateDetails d) {
    // a second finger mid-gesture means zoom: drop the half-made change and move the view instead
    if (d.pointerCount > 1 && _mode != _Mode.view) {
      setState(() {
        _marks = List.of(_before);
        _mode = _Mode.view;
        _active = null;
        _finger = null;
      });
      _gestureStart = d.localFocalPoint;
      _viewStart = _view.value.clone();
      return;
    }
    switch (_mode) {
      case _Mode.place:
        setState(() {
          _finger = d.localFocalPoint;
          _marks[_active!] = _toNorm(d.localFocalPoint);
        });
      case _Mode.drag:
        // a third of the finger's travel, so a mark a few pixels wide can be set exactly
        final delta = (d.localFocalPoint - _gestureStart) / 3 / _scale;
        setState(() {
          _finger = d.localFocalPoint;
          _marks[_active!] = Offset(
            (_markStart.dx + delta.dx / _image!.width).clamp(0.0, 1.0),
            (_markStart.dy + delta.dy / _image!.height).clamp(0.0, 1.0),
          );
        });
      case _Mode.view:
        final base = _viewStart.getMaxScaleOnAxis();
        final s =
            (base * d.scale).clamp(_fitScale * 0.8, _fitScale * 16) / base;
        _view.value = Matrix4.identity()
          ..translateByDouble(d.localFocalPoint.dx, d.localFocalPoint.dy, 0, 1)
          ..scaleByDouble(s, s, 1, 1)
          ..translateByDouble(-_gestureStart.dx, -_gestureStart.dy, 0, 1)
          ..multiply(_viewStart);
      case _Mode.none:
        break;
    }
  }

  void _end(ScaleEndDetails _) {
    if (!listEquals(_before, _marks)) {
      _undo.add(_before);
      if (_active == _suspect) _suspect = null;
      widget.onEdited?.call();
    }
    setState(() {
      _mode = _Mode.none;
      _active = null;
      _finger = null;
    });
  }

  void _undoLast() {
    if (_undo.isEmpty) return;
    setState(() => _marks = _undo.removeLast());
  }

  // a corner behind the batter or the bowler is skipped; the server solves from the other seven
  void _hide() {
    setState(() {
      _undo.add(List.of(_marks));
      _marks.add(null);
    });
    widget.onEdited?.call();
  }

  // tapped in the wrong order, the server would solve a camera that can't exist
  String? _orderProblem() {
    for (final (i, end) in [(0, 'far'), (4, 'near')]) {
      // with a corner hidden the set can't be checked this way
      if (_marks.sublist(i, i + 4) case [
        final tl?,
        final tr?,
        final br?,
        final bl?,
      ] when tl.dy + tr.dy >= br.dy + bl.dy || tl.dx + bl.dx >= tr.dx + br.dx) {
        return 'The $end stumps look marked out of order. Undo and mark '
            'top left, top right, bottom right, then bottom left.';
      }
    }
    return null;
  }

  void _done() {
    final problem = _orderProblem();
    if (problem == null) return widget.onComplete(List.unmodifiable(_marks));
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(problem)));
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _Header(
          next: _mode == _Mode.place ? _active! : _marks.length,
          suspect: _suspect,
          onHide:
              _mode == _Mode.none && _marks.length < 8 && !_marks.contains(null)
              ? _hide
              : null,
        ),
        Expanded(child: _canvas()),
        _Bar(
          canUndo: _undo.isNotEmpty,
          onUndo: _undoLast,
          onFit: _viewport == null ? null : () => _fit(_viewport!),
          label: widget.actionLabel,
          onDone: _marks.length == 8 && _mode == _Mode.none ? _done : null,
          hand: widget.hand,
          onHand: widget.onHand,
        ),
      ],
    );
  }

  Widget _canvas() {
    final theme = Theme.of(context);
    if (_failed) {
      return ColoredBox(
        color: AppColors.video,
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.xl),
            child: Text(
              "This frame can't be shown. Go back and pick another one.",
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyLarge?.copyWith(
                color: AppColors.onVideo,
              ),
            ),
          ),
        ),
      );
    }
    final img = _image;
    if (img == null) {
      return const ColoredBox(
        color: AppColors.video,
        child: Center(
          child: CircularProgressIndicator(color: AppColors.onVideo),
        ),
      );
    }
    return LayoutBuilder(
      builder: (context, box) {
        final viewport = box.biggest;
        // turning the phone changes the viewport, so fit the frame again
        if (viewport != _viewport) {
          _viewport = viewport;
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted) setState(() => _fit(viewport));
          });
        }
        final finger = _finger;
        final active = _active;
        return ClipRect(
          child: ColoredBox(
            color: AppColors.video,
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onScaleStart: _start,
              onScaleUpdate: _update,
              onScaleEnd: _end,
              child: Stack(
                children: [
                  // sized to the frame itself, not the screen, so the view matrix maps frame pixels
                  Positioned(
                    left: 0,
                    top: 0,
                    width: img.width,
                    height: img.height,
                    child: AnimatedBuilder(
                      animation: _view,
                      builder: (context, child) =>
                          Transform(transform: _view.value, child: child),
                      child: Image.memory(
                        widget.frame,
                        fit: BoxFit.fill,
                        gaplessPlayback: true,
                      ),
                    ),
                  ),
                  Positioned.fill(
                    child: CustomPaint(
                      painter: _MarksPainter(
                        norm: _marks,
                        image: img,
                        active: active,
                        suspect: _suspect,
                        view: _view,
                      ),
                    ),
                  ),
                  if (finger != null && active != null)
                    _Loupe(
                      at: _toScreen(_marks[active]!),
                      finger: finger,
                      viewport: viewport,
                    ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

/// Which mark is next, in words and on a small drawing of both sets of stumps.
class _Header extends StatelessWidget {
  const _Header({required this.next, required this.suspect, this.onHide});
  final int next;
  final int? suspect;
  final VoidCallback? onHide;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final s = suspect;
    final (title, help) = s != null
        ? (
            'Mark ${s + 1} is off',
            "The server says ${markName(s).toLowerCase()} doesn't line up "
                'with the others. Zoom in and drag it onto the corner.',
          )
        : next >= 8
        ? (
            'All 8 corners marked',
            'Zoom in with two fingers to check each one. Drag a mark to fine-tune it.',
          )
        : (
            '${next + 1} of 8: ${markName(next)}',
            '${_cornerHelp[next % 4]}. Hold and slide to aim, lift to place.',
          );
    return Container(
      color: s != null ? scheme.errorContainer : scheme.surfaceContainerLow,
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.md,
        AppSpacing.md,
        AppSpacing.md,
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: theme.textTheme.titleMedium?.copyWith(
                    color: s != null ? scheme.onErrorContainer : null,
                  ),
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  help,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: s != null
                        ? scheme.onErrorContainer
                        : scheme.onSurfaceVariant,
                  ),
                ),
                if (onHide != null && s == null)
                  TextButton(
                    style: TextButton.styleFrom(
                      padding: EdgeInsets.zero,
                      visualDensity: VisualDensity.compact,
                    ),
                    onPressed: onHide,
                    child: const Text("Can't see this one"),
                  ),
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Semantics(
            excludeSemantics: true,
            child: CustomPaint(
              size: const Size(64, 76),
              painter: _GuidePainter(
                next: s ?? next,
                ink: scheme.onSurfaceVariant,
                done: scheme.primary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Two wickets the way the camera sees them, far one small, with the next corner ringed.
class _GuidePainter extends CustomPainter {
  _GuidePainter({required this.next, required this.ink, required this.done});
  final int next;
  final Color ink;
  final Color done;

  @override
  void paint(Canvas canvas, Size size) {
    final far = Rect.fromCenter(
      center: Offset(size.width / 2, 12),
      width: 16,
      height: 18,
    );
    final near = Rect.fromCenter(
      center: Offset(size.width / 2, 52),
      width: 34,
      height: 40,
    );
    final stump = Paint()
      ..color = ink.withValues(alpha: 0.6)
      ..strokeWidth = 1.5;
    for (final r in [far, near]) {
      for (final x in [r.left, r.center.dx, r.right]) {
        canvas.drawLine(Offset(x, r.top), Offset(x, r.bottom), stump);
      }
    }
    for (var i = 0; i < 8; i++) {
      final r = i < 4 ? far : near;
      final p = [r.topLeft, r.topRight, r.bottomRight, r.bottomLeft][i % 4];
      if (i == next) {
        canvas.drawCircle(p, 6, Paint()..color = AppColors.track);
        canvas.drawCircle(
          p,
          9,
          Paint()
            ..color = AppColors.track.withValues(alpha: 0.5)
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2,
        );
      } else {
        canvas.drawCircle(
          p,
          3.5,
          i < next
              ? (Paint()..color = done)
              : (Paint()
                  ..color = ink
                  ..style = PaintingStyle.stroke
                  ..strokeWidth = 1.2),
        );
      }
    }
  }

  @override
  bool shouldRepaint(_GuidePainter old) =>
      old.next != next || old.ink != ink || old.done != done;
}

class _Bar extends StatelessWidget {
  const _Bar({
    required this.canUndo,
    required this.onUndo,
    required this.onFit,
    required this.label,
    required this.onDone,
    required this.hand,
    required this.onHand,
  });
  final bool canUndo;
  final VoidCallback onUndo;
  final VoidCallback? onFit;
  final String label;
  final VoidCallback? onDone;
  final String? hand;
  final ValueChanged<String>? onHand;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return ColoredBox(
      color: scheme.surfaceContainerLow,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.sm,
            AppSpacing.lg,
            AppSpacing.md,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.undo),
                    tooltip: 'Undo',
                    onPressed: canUndo ? onUndo : null,
                  ),
                  IconButton(
                    icon: const Icon(Icons.fit_screen_outlined),
                    tooltip: 'Show the whole frame',
                    onPressed: onFit,
                  ),
                  const Spacer(),
                  if (hand case final h?) ...[
                    Flexible(
                      flex: 3,
                      child: ActionChip(
                        avatar: const Icon(Icons.swap_horiz, size: 18),
                        label: Text(
                          h == 'left' ? 'Left-handed' : 'Right-handed',
                          overflow: TextOverflow.ellipsis,
                        ),
                        tooltip: 'Switch the batter\'s hand',
                        onPressed: onHand == null
                            ? null
                            : () => onHand!(h == 'left' ? 'right' : 'left'),
                      ),
                    ),
                    const SizedBox(width: AppSpacing.sm),
                  ],
                  const Flexible(flex: 4, child: PitchSetupChip()),
                ],
              ),
              const SizedBox(height: AppSpacing.sm),
              FilledButton(onPressed: onDone, child: Text(label)),
            ],
          ),
        ),
      ),
    );
  }
}

/// A magnified view of the mark being placed, kept clear of the finger so the corner stays visible.
class _Loupe extends StatelessWidget {
  const _Loupe({
    required this.at,
    required this.finger,
    required this.viewport,
  });
  final Offset at;
  final Offset finger;
  final Size viewport;

  static const _size = 132.0;

  @override
  Widget build(BuildContext context) {
    // above the finger, or below it near the top edge
    final up = finger.dy - _size - 48;
    final centre = Offset(
      finger.dx.clamp(
        _size / 2,
        math.max(_size / 2, viewport.width - _size / 2),
      ),
      up >= 0 ? up + _size / 2 : finger.dy + 48 + _size / 2,
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
              side: BorderSide(color: AppColors.onVideo, width: 2),
            ),
          ),
          child: const CustomPaint(painter: _LoupeCross()),
        ),
      ),
    );
  }
}

class _LoupeCross extends CustomPainter {
  const _LoupeCross();

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final p = Paint()
      ..color = AppColors.track
      ..strokeWidth = 1.5;
    for (final d in const [
      Offset(1, 0),
      Offset(-1, 0),
      Offset(0, 1),
      Offset(0, -1),
    ]) {
      canvas.drawLine(c + d * 6, c + d * 22, p);
    }
  }

  @override
  bool shouldRepaint(_LoupeCross old) => false;
}

/// The marks in screen space, so they stay thin and never cover a corner however far you zoom.
class _MarksPainter extends CustomPainter {
  _MarksPainter({
    required this.norm,
    required this.image,
    required this.active,
    required this.suspect,
    required this.view,
  }) : super(repaint: view);
  final List<Offset?> norm;
  final Size image;
  final int? active;
  final int? suspect;
  final TransformationController view;

  @override
  void paint(Canvas canvas, Size size) {
    final marks = [
      for (final m in norm)
        m == null
            ? null
            : MatrixUtils.transformPoint(
                view.value,
                Offset(m.dx * image.width, m.dy * image.height),
              ),
    ];
    // every 4 marks outline one set, so the two never join up
    for (var i = 0; i < marks.length; i += 4) {
      final q = marks
          .sublist(i, math.min(i + 4, marks.length))
          .nonNulls
          .toList();
      final path = Path()..addPolygon(q, q.length == 4);
      if (q.length == 4) {
        canvas.drawPath(
          path,
          Paint()..color = AppColors.track.withValues(alpha: 0.12),
        );
      }
      canvas.drawPath(
        path,
        Paint()
          ..color = AppColors.track.withValues(alpha: 0.9)
          ..strokeWidth = 1.2
          ..style = PaintingStyle.stroke,
      );
    }
    for (var i = 0; i < marks.length; i++) {
      final p = marks[i];
      if (p == null) continue;
      final colour = i == suspect ? AppColors.umpiresCall : AppColors.track;
      // crosshair with an open centre, so the exact corner stays visible
      final cross = Paint()
        ..color = colour
        ..strokeWidth = i == active ? 2 : 1.4;
      for (final d in const [
        Offset(1, 0),
        Offset(-1, 0),
        Offset(0, 1),
        Offset(0, -1),
      ]) {
        canvas.drawLine(p + d * 4, p + d * 14, cross);
      }
      if (i == suspect) {
        canvas.drawCircle(
          p,
          22,
          Paint()
            ..color = colour
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2.5,
        );
      }
      // numbered dot off the corner, away from its set, so dots never cover a corner or each other
      final out = const [
        Offset(-1, -1),
        Offset(1, -1),
        Offset(1, 1),
        Offset(-1, 1),
      ][i % 4];
      final dot = p + out * 13;
      canvas.drawCircle(dot, 8, Paint()..color = colour);
      final tp = TextPainter(
        text: TextSpan(
          text: '${i + 1}',
          style: TextStyle(
            color: AppColors.onVerdict(colour),
            fontSize: 10,
            fontWeight: FontWeight.w700,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, dot - Offset(tp.width / 2, tp.height / 2));
    }
  }

  @override
  bool shouldRepaint(_MarksPainter old) => true;
}

/// Asks before leaving a frame whose stump marks would be lost; true means leave.
Future<bool> confirmDropMarks(BuildContext context) async {
  final leave = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('Leave without your marks?'),
      content: const Text(
        'The stump marks on this frame will be lost, and you will have to mark them again.',
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, false),
          child: const Text('Keep marking'),
        ),
        TextButton(
          onPressed: () => Navigator.pop(context, true),
          child: const Text('Leave'),
        ),
      ],
    ),
  );
  return leave ?? false;
}

/// Full-screen marking on a saved frame, for sending a ball again with better marks.
class MarkStumpsScreen extends StatefulWidget {
  const MarkStumpsScreen({
    super.key,
    required this.frame,
    required this.marks,
    this.suspect,
  });
  final Uint8List frame;
  final List<Offset?> marks;
  final int? suspect;

  @override
  State<MarkStumpsScreen> createState() => _MarkStumpsScreenState();
}

class _MarkStumpsScreenState extends State<MarkStumpsScreen> {
  bool _edited = false;

  @override
  Widget build(BuildContext context) {
    return PopScope<List<Offset?>>(
      canPop: !_edited,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop || !await confirmDropMarks(context)) return;
        if (context.mounted) Navigator.pop(context);
      },
      child: Scaffold(
        appBar: AppBar(title: const Text('Mark the stumps')),
        body: StumpMarker(
          frame: widget.frame,
          initialMarks: widget.marks,
          suspect: widget.suspect,
          actionLabel: 'Send again',
          onEdited: () {
            if (!_edited) setState(() => _edited = true);
          },
          onComplete: (m) => Navigator.pop(context, m),
        ),
      ),
    );
  }
}
