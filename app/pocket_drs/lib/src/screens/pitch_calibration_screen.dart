import 'dart:io';
import 'dart:math' as math;
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:video_thumbnail/video_thumbnail.dart';

import '../analysis/calibration_config.dart';
import '../analysis/pitch_calibration.dart';
import '../utils/pitch_store.dart';
import '../widgets/image_marker.dart';
import '../widgets/video_frame_selector.dart';
import 'post_calibration_3d_screen.dart';

enum _Step { video, frame, pitch, stumpsStriker, stumpsBowler, review, ball, done }

class PitchCalibrationScreen extends StatefulWidget {
  const PitchCalibrationScreen({
    super.key,
    required this.pitchId,
    required this.pitchName,
  });

  final String pitchId;
  final String pitchName;

  @override
  State<PitchCalibrationScreen> createState() => _PitchCalibrationScreenState();
}

class _PitchCalibrationScreenState extends State<PitchCalibrationScreen> {
  final _picker = ImagePicker();
  final _store = PitchStore();

  _Step _step = _Step.video;
  XFile? _video;
  String? _framePath;
  List<Offset>? _pitchCorners;
  List<Offset>? _strikerStumps;
  List<Offset>? _bowlerStumps;
  XFile? _ballImage;
  bool _saving = false;

  List<Offset>? get _stumpMarkers {
    final a = _strikerStumps;
    final b = _bowlerStumps;
    if (a == null || b == null) return null;
    if (a.length != 2 || b.length != 2) return null;
    // 0: striker base, 1: striker top, 2: bowler base, 3: bowler top
    return List.unmodifiable(<Offset>[a[0], a[1], b[0], b[1]]);
  }

  Future<void> _pickVideo(ImageSource source) async {
    try {
      final video = await _picker.pickVideo(source: source);
      if (video != null && mounted) {
        setState(() {
          _video = video;
          _step = _Step.frame;
        });
      }
    } catch (e) {
      _showError('Failed to get video');
    }
  }

  Future<void> _onFrameSelected(Duration timestamp) async {
    if (_video == null) return;
    try {
      final tempDir = await getTemporaryDirectory();
      final framePath = '${tempDir.path}/cal_${timestamp.inMilliseconds}.jpg';
      final bytes = await VideoThumbnail.thumbnailData(
        video: _video!.path,
        imageFormat: ImageFormat.JPEG,
        timeMs: timestamp.inMilliseconds,
        quality: 95,
      );
      if (bytes == null) {
        _showError('Failed to extract frame');
        return;
      }
      await File(framePath).writeAsBytes(bytes);
      if (mounted) {
        setState(() {
          _framePath = framePath;
          _step = _Step.pitch;
        });
      }
    } catch (e) {
      _showError('Frame extraction failed');
    }
  }

  void _onPitchComplete(List<Offset> markers) {
    setState(() {
      _pitchCorners = markers;
      _step = _Step.stumpsStriker;
    });
  }

  double _distPointToLine(Offset p, Offset a, Offset b) {
    // Distance from point to infinite line AB in normalized space.
    final ab = b - a;
    final ap = p - a;
    final denom = (ab.dx * ab.dx + ab.dy * ab.dy);
    if (denom <= 1e-12) return (p - a).distance;
    final cross = (ap.dx * ab.dy - ap.dy * ab.dx).abs();
    final len = math.sqrt(denom);
    return cross / len;
  }

  bool _looksLikeStrikerEnd(Offset base) {
    final corners = _pitchCorners;
    if (corners == null || corners.length != 4) return true;
    final strikerLineA = corners[0];
    final strikerLineB = corners[1];
    final bowlerLineA = corners[3];
    final bowlerLineB = corners[2];
    final dStriker = _distPointToLine(base, strikerLineA, strikerLineB);
    final dBowler = _distPointToLine(base, bowlerLineA, bowlerLineB);
    return dStriker <= dBowler;
  }

  bool _validateStumpPair(List<Offset> pair, {required String endName}) {
    if (pair.length != 2) {
      _showError('Please mark both base and top for $endName end');
      return false;
    }
    final base = pair[0];
    final top = pair[1];
    // In screen space Y increases downward. Top should be above base.
    if (top.dy >= base.dy) {
      _showError('For $endName end: tap the base first, then the top of the stumps');
      return false;
    }
    return true;
  }

  Future<void> _onStrikerStumpsComplete(List<Offset> markers) async {
    if (!_validateStumpPair(markers, endName: 'striker')) return;
    final base = markers[0];
    if (!_looksLikeStrikerEnd(base)) {
      final swap = await _confirmSwapEnds(
        title: 'Looks like bowler end',
        message:
            'The stump base you marked is closer to the bowler-end boundary. Do you want to treat this as the bowler-end stumps instead?',
      );
      if (!mounted) return;
      if (swap) {
        setState(() {
          _bowlerStumps = markers;
          _step = _Step.stumpsStriker;
        });
        return;
      }
    }
    setState(() {
      _strikerStumps = markers;
      _step = _Step.stumpsBowler;
    });
  }

  Future<void> _onBowlerStumpsComplete(List<Offset> markers) async {
    if (!_validateStumpPair(markers, endName: 'bowler')) return;
    final base = markers[0];
    if (_looksLikeStrikerEnd(base)) {
      final swap = await _confirmSwapEnds(
        title: 'Looks like striker end',
        message:
            'The stump base you marked is closer to the striker-end boundary. Do you want to treat this as the striker-end stumps instead?',
      );
      if (!mounted) return;
      if (swap) {
        setState(() {
          _strikerStumps = markers;
          _step = _Step.stumpsBowler;
        });
        return;
      }
    }
    setState(() {
      _bowlerStumps = markers;
      _step = _Step.review;
    });
  }

  Future<bool> _confirmSwapEnds({required String title, required String message}) async {
    final res = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Keep as-is')),
          FilledButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Swap ends')),
        ],
      ),
    );
    return res ?? false;
  }

  Future<void> _pickBallImage(ImageSource source) async {
    try {
      final img = await _picker.pickImage(source: source, imageQuality: 90);
      if (!mounted) return;
      if (img == null) return;
      setState(() {
        _ballImage = img;
      });
    } catch (e) {
      _showError('Failed to get ball photo');
    }
  }

  Future<ui.Size> _decodeImageSize(String path) async {
    final bytes = await File(path).readAsBytes();
    final codec = await ui.instantiateImageCodec(bytes);
    final frame = await codec.getNextFrame();
    final size = ui.Size(frame.image.width.toDouble(), frame.image.height.toDouble());
    frame.image.dispose();
    return size;
  }

  Future<String?> _persistBallImage(String pitchId, XFile image) async {
    try {
      final dir = await getApplicationDocumentsDirectory();
      final pitchDir = Directory('${dir.path}/pocket_drs/pitches/$pitchId');
      if (!await pitchDir.exists()) {
        await pitchDir.create(recursive: true);
      }
      final outPath = '${pitchDir.path}/ball.jpg';
      await File(outPath).writeAsBytes(await image.readAsBytes());
      return outPath;
    } catch (_) {
      return null;
    }
  }

  Future<void> _saveCalibration() async {
    if (_pitchCorners == null || _pitchCorners!.length != 4) return;
    setState(() => _saving = true);
    try {
      if (_framePath == null) throw StateError('Missing calibration frame');
      final size = await _decodeImageSize(_framePath!);
      final w = size.width;
      final h = size.height;

      final pitchPts = _pitchCorners!.map((p) => Offset(p.dx * w, p.dy * h)).toList();
      final stumpMarkers = _stumpMarkers;
      final stumpPts = stumpMarkers?.map((p) => Offset(p.dx * w, p.dy * h)).toList();

      String? ballPath;
      if (_ballImage != null) {
        ballPath = await _persistBallImage(widget.pitchId, _ballImage!);
      }

      final calibration = CalibrationConfig(
        pitchLengthM: 20.12,
        pitchWidthM: 3.05,
        stumpHeightM: 0.711,
        cameraHeightM: 1.5,
        cameraDistanceToStumpsM: 15.0,
        cameraLateralOffsetM: 0.0,
        ballImagePath: ballPath,
        pitchCalibration: PitchCalibration(
          imagePoints: pitchPts,
          stumpPoints: stumpPts,
          imageSizePx: Size(w, h),
          imagePointsNorm: List.unmodifiable(_pitchCorners!),
          stumpPointsNorm: stumpMarkers == null ? null : List.unmodifiable(stumpMarkers),
        ),
      );

      final pitch = await _store.loadById(widget.pitchId);
      if (pitch == null) throw StateError('Pitch not found');
      await _store.update(pitch.copyWith(calibration: calibration, updatedAt: DateTime.now()));

      if (mounted) {
        // Navigate to post-calibration 3D view
        await Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => PostCalibration3DScreen(
              pitchName: widget.pitchName,
              calibration: calibration.pitchCalibration!,
            ),
          ),
        );
        // Then pop back to pitch list
        if (mounted) Navigator.of(context).pop(true);
      }
    } catch (e) {
      _showError('Save failed');
      setState(() => _step = _Step.ball);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  void _goBack() {
    setState(() {
      switch (_step) {
        case _Step.frame:
          _step = _Step.video;
          _video = null;
        case _Step.pitch:
          _step = _Step.frame;
          _framePath = null;
        case _Step.stumpsStriker:
          _step = _Step.pitch;
          _pitchCorners = null;
        case _Step.stumpsBowler:
          _step = _Step.stumpsStriker;
          _strikerStumps = null;
        case _Step.review:
          _step = _Step.stumpsBowler;
          _bowlerStumps = null;
        case _Step.ball:
          _step = _Step.review;
          _ballImage = null;
        default:
          Navigator.of(context).pop();
      }
    });
  }

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), behavior: SnackBarBehavior.floating),
    );
  }

  int get _stepIndex => _step.index;
  static const _steps = ['Video', 'Frame', 'Pitch', 'Striker', 'Bowler', 'Review', 'Ball'];

  String? get _stepHint {
    return switch (_step) {
      _Step.pitch => 'Tap pitch corners clockwise starting at striker end.',
      _Step.stumpsStriker || _Step.stumpsBowler => 'Tap stump base first, then stump top. Pinch to zoom.',
      _Step.review => 'Zoom in and confirm markings. Use Edit to fix anything.',
      _ => null,
    };
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final hint = _stepHint;
    return Scaffold(
      backgroundColor: theme.colorScheme.surface,
      appBar: _step != _Step.done
          ? AppBar(
              backgroundColor: Colors.transparent,
              elevation: 0,
              leading: IconButton(
                icon: const Icon(Icons.arrow_back),
                onPressed: _goBack,
              ),
              title: Text(widget.pitchName),
              bottom: PreferredSize(
                preferredSize: Size.fromHeight(hint == null ? 40 : 64),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _StepIndicator(current: _stepIndex, steps: _steps),
                    if (hint != null)
                      Padding(
                        padding: const EdgeInsets.fromLTRB(24, 0, 24, 10),
                        child: Text(
                          hint,
                          textAlign: TextAlign.center,
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            )
          : null,
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    switch (_step) {
      case _Step.video:
        return _VideoStep(onPick: _pickVideo);
      case _Step.frame:
        return _video == null
            ? const SizedBox()
            : VideoFrameSelector(videoPath: _video!.path, onFrameSelected: _onFrameSelected);
      case _Step.pitch:
        return _framePath == null
            ? const SizedBox()
            : ImageMarker(
                key: const ValueKey('pitch_markers'),
                imagePath: _framePath!,
                maxMarkers: 4,
                title: 'Mark Pitch Corners',
                subtitle: 'Tap corners clockwise starting at striker end (near stumps)',
                markerLabels: const ['Striker Left', 'Striker Right', 'Bowler Right', 'Bowler Left'],
                initialMarkers: _pitchCorners,
                showHeader: false,
                onComplete: _onPitchComplete,
              );
      case _Step.stumpsStriker:
        return _framePath == null
            ? const SizedBox()
            : ImageMarker(
                key: const ValueKey('stumps_striker'),
                imagePath: _framePath!,
                maxMarkers: 2,
                title: 'Mark Striker-End Stumps',
                subtitle: 'Tap the stump BASE then stump TOP (pinch to zoom)',
                markerLabels: const ['Striker Base', 'Striker Top'],
                initialMarkers: _strikerStumps,
                guides: _buildGuides(),
                highlightGuideIndex: 1,
                showHeader: false,
                onComplete: _onStrikerStumpsComplete,
              );
      case _Step.stumpsBowler:
        return _framePath == null
            ? const SizedBox()
            : ImageMarker(
                key: const ValueKey('stumps_bowler'),
                imagePath: _framePath!,
                maxMarkers: 2,
                title: 'Mark Bowler-End Stumps',
                subtitle: 'Tap the stump BASE then stump TOP (pinch to zoom)',
                markerLabels: const ['Bowler Base', 'Bowler Top'],
                initialMarkers: _bowlerStumps,
                guides: _buildGuides(),
                highlightGuideIndex: 2,
                showHeader: false,
                onComplete: _onBowlerStumpsComplete,
              );
      case _Step.review:
        return _framePath == null
            ? const SizedBox()
            : _CalibrationReviewStep(
                imagePath: _framePath!,
                pitchCorners: _pitchCorners!,
                strikerStumps: _strikerStumps,
                bowlerStumps: _bowlerStumps,
                onEditPitch: () => setState(() => _step = _Step.pitch),
                onEditStriker: () => setState(() => _step = _Step.stumpsStriker),
                onEditBowler: () => setState(() => _step = _Step.stumpsBowler),
                onContinue: () => setState(() => _step = _Step.ball),
              );
      case _Step.ball:
        return _BallStep(
          ballImage: _ballImage,
          onPickCamera: () => _pickBallImage(ImageSource.camera),
          onPickGallery: () => _pickBallImage(ImageSource.gallery),
          onContinue: () {
            setState(() => _step = _Step.done);
            _saveCalibration();
          },
        );
      case _Step.done:
        return _SavingOverlay(saving: _saving);
    }
  }

  List<List<Offset>> _buildGuides() {
    final corners = _pitchCorners;
    if (corners == null || corners.length != 4) return const [];
    // 0..3 already in order used by UI.
    final outline = <Offset>[corners[0], corners[1], corners[2], corners[3], corners[0]];
    final strikerLine = <Offset>[corners[0], corners[1]];
    final bowlerLine = <Offset>[corners[3], corners[2]];
    return <List<Offset>>[
      outline,
      strikerLine,
      bowlerLine,
    ];
  }
}

class _CalibrationReviewStep extends StatefulWidget {
  const _CalibrationReviewStep({
    required this.imagePath,
    required this.pitchCorners,
    required this.strikerStumps,
    required this.bowlerStumps,
    required this.onEditPitch,
    required this.onEditStriker,
    required this.onEditBowler,
    required this.onContinue,
  });

  final String imagePath;
  final List<Offset> pitchCorners;
  final List<Offset>? strikerStumps;
  final List<Offset>? bowlerStumps;
  final VoidCallback onEditPitch;
  final VoidCallback onEditStriker;
  final VoidCallback onEditBowler;
  final VoidCallback onContinue;

  @override
  State<_CalibrationReviewStep> createState() => _CalibrationReviewStepState();
}

class _CalibrationReviewStepState extends State<_CalibrationReviewStep> {
  ui.Size? _size;
  bool _loading = true;
  final TransformationController _transform = TransformationController();
  bool _didInitTransform = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final bytes = await File(widget.imagePath).readAsBytes();
    final codec = await ui.instantiateImageCodec(bytes);
    final frame = await codec.getNextFrame();
    final s = ui.Size(frame.image.width.toDouble(), frame.image.height.toDouble());
    frame.image.dispose();
    if (!mounted) return;
    setState(() {
      _size = s;
      _loading = false;
    });
  }

  void _fit(Size viewport) {
    final s = _size;
    if (s == null) return;
    final iw = s.width;
    final ih = s.height;
    final scale = (viewport.width / iw).clamp(0.05, 10.0);
    final scale2 = (viewport.height / ih).clamp(0.05, 10.0);
    final k = scale < scale2 ? scale : scale2;
    final dx = (viewport.width - iw * k) / 2.0;
    final dy = (viewport.height - ih * k) / 2.0;
    _transform.value = Matrix4.identity()
      ..translate(dx, dy)
      ..scale(k);
  }

  @override
  void dispose() {
    _transform.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final size = _size;

    return Column(
      children: [
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : LayoutBuilder(
                  builder: (context, box) {
                    final viewport = Size(box.maxWidth, box.maxHeight);
                    if (!_didInitTransform) {
                      _didInitTransform = true;
                      WidgetsBinding.instance.addPostFrameCallback((_) {
                        if (!mounted) return;
                        _fit(viewport);
                      });
                    }

                    return Container(
                      color: theme.colorScheme.surfaceContainerLowest,
                      child: InteractiveViewer(
                        transformationController: _transform,
                        minScale: 0.5,
                        maxScale: 12.0,
                        boundaryMargin: const EdgeInsets.all(48),
                        constrained: false,
                        child: SizedBox(
                          width: size!.width,
                          height: size.height,
                          child: Stack(
                            fit: StackFit.expand,
                            children: [
                              Image.file(File(widget.imagePath), fit: BoxFit.fill),
                              CustomPaint(
                                painter: _CalibrationReviewPainter(
                                  pitchCorners: widget.pitchCorners,
                                  strikerStumps: widget.strikerStumps,
                                  bowlerStumps: widget.bowlerStumps,
                                  accent: theme.colorScheme.primary,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    );
                  },
                ),
        ),
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: theme.colorScheme.surface,
            border: Border(top: BorderSide(color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3))),
          ),
          child: SafeArea(
            top: false,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    OutlinedButton.icon(
                      onPressed: widget.onEditPitch,
                      icon: const Icon(Icons.crop_free),
                      label: const Text('Edit pitch corners'),
                    ),
                    OutlinedButton.icon(
                      onPressed: widget.onEditStriker,
                      icon: const Icon(Icons.sports_cricket),
                      label: const Text('Edit striker stumps'),
                    ),
                    OutlinedButton.icon(
                      onPressed: widget.onEditBowler,
                      icon: const Icon(Icons.sports_cricket_outlined),
                      label: const Text('Edit bowler stumps'),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: widget.onContinue,
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

class _CalibrationReviewPainter extends CustomPainter {
  _CalibrationReviewPainter({
    required this.pitchCorners,
    required this.strikerStumps,
    required this.bowlerStumps,
    required this.accent,
  });

  final List<Offset> pitchCorners;
  final List<Offset>? strikerStumps;
  final List<Offset>? bowlerStumps;
  final Color accent;

  @override
  void paint(Canvas canvas, Size size) {
    if (pitchCorners.length != 4) return;

    final pts = pitchCorners
        .map((p) => Offset(p.dx * size.width, p.dy * size.height))
        .toList(growable: false);

    final outline = Path()..moveTo(pts[0].dx, pts[0].dy);
    outline.lineTo(pts[1].dx, pts[1].dy);
    outline.lineTo(pts[2].dx, pts[2].dy);
    outline.lineTo(pts[3].dx, pts[3].dy);
    outline.close();

    canvas.drawPath(outline, Paint()..color = accent.withValues(alpha: 0.10));
    canvas.drawPath(
      outline,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.5
        ..color = accent.withValues(alpha: 0.9),
    );

    void drawStumps(List<Offset>? pair, Color c, String label) {
      if (pair == null || pair.length != 2) return;
      final b = Offset(pair[0].dx * size.width, pair[0].dy * size.height);
      final t = Offset(pair[1].dx * size.width, pair[1].dy * size.height);
      final p = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3
        ..color = c;
      canvas.drawLine(b, t, p);
      canvas.drawCircle(b, 8, Paint()..color = c.withValues(alpha: 0.25));
      canvas.drawCircle(b, 5, Paint()..color = c);
      canvas.drawCircle(t, 8, Paint()..color = c.withValues(alpha: 0.25));
      canvas.drawCircle(t, 5, Paint()..color = c);

      final tp = TextPainter(
        text: TextSpan(
          text: label,
          style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, t + const Offset(10, -10));
    }

    drawStumps(strikerStumps, const Color(0xFF22C55E), 'Striker');
    drawStumps(bowlerStumps, const Color(0xFFF59E0B), 'Bowler');
  }

  @override
  bool shouldRepaint(_CalibrationReviewPainter oldDelegate) {
    return oldDelegate.pitchCorners != pitchCorners ||
        oldDelegate.strikerStumps != strikerStumps ||
        oldDelegate.bowlerStumps != bowlerStumps ||
        oldDelegate.accent != accent;
  }
}

class _BallStep extends StatelessWidget {
  const _BallStep({
    required this.ballImage,
    required this.onPickCamera,
    required this.onPickGallery,
    required this.onContinue,
  });

  final XFile? ballImage;
  final VoidCallback onPickCamera;
  final VoidCallback onPickGallery;
  final VoidCallback onContinue;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Ball Photo', style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Text(
            'Take or choose a clear photo of the match ball. This helps future improvements in detection (optional, but recommended).',
            style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),
          const SizedBox(height: 24),
          Expanded(
            child: Container(
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainer,
                borderRadius: BorderRadius.circular(16),
              ),
              clipBehavior: Clip.antiAlias,
              child: ballImage == null
                  ? Center(
                      child: Text(
                        'No ball photo selected',
                        style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                      ),
                    )
                  : Image.file(File(ballImage!.path), fit: BoxFit.contain),
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: onPickCamera,
                  icon: const Icon(Icons.photo_camera_outlined),
                  label: const Text('Camera'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: onPickGallery,
                  icon: const Icon(Icons.photo_outlined),
                  label: const Text('Gallery'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: onContinue,
            child: const Text('Save Calibration'),
          ),
        ],
      ),
    );
  }
}

class _StepIndicator extends StatelessWidget {
  const _StepIndicator({required this.current, required this.steps});
  final int current;
  final List<String> steps;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 8),
      child: Row(
        children: List.generate(steps.length, (i) {
          final active = i == current;
          final done = i < current;
          return Expanded(
            child: Row(
              children: [
                if (i > 0)
                  Expanded(
                    child: Container(
                      height: 2,
                      color: done ? theme.colorScheme.primary : theme.colorScheme.outlineVariant.withValues(alpha: 0.3),
                    ),
                  ),
                Container(
                  width: 28,
                  height: 28,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: done
                        ? theme.colorScheme.primary
                        : active
                            ? theme.colorScheme.primaryContainer
                            : Colors.transparent,
                    border: Border.all(
                      color: done || active ? theme.colorScheme.primary : theme.colorScheme.outlineVariant,
                      width: 2,
                    ),
                  ),
                  child: Center(
                    child: done
                        ? Icon(Icons.check, size: 14, color: theme.colorScheme.onPrimary)
                        : Text(
                            '${i + 1}',
                            style: theme.textTheme.labelSmall?.copyWith(
                              color: active ? theme.colorScheme.primary : theme.colorScheme.onSurfaceVariant,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                  ),
                ),
                if (i < steps.length - 1)
                  Expanded(
                    child: Container(
                      height: 2,
                      color: done ? theme.colorScheme.primary : theme.colorScheme.outlineVariant.withValues(alpha: 0.3),
                    ),
                  ),
              ],
            ),
          );
        }),
      ),
    );
  }
}

class _VideoStep extends StatelessWidget {
  const _VideoStep({required this.onPick});
  final void Function(ImageSource) onPick;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 80,
              height: 80,
              decoration: BoxDecoration(
                color: theme.colorScheme.primaryContainer,
                shape: BoxShape.circle,
              ),
              child: Icon(Icons.videocam_outlined, size: 36, color: theme.colorScheme.primary),
            ),
            const SizedBox(height: 24),
            Text(
              'Calibration Video',
              style: theme.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 8),
            Text(
              'Record a video showing the full pitch\nwith visible stumps at both ends',
              style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 40),
            SizedBox(
              width: 200,
              child: FilledButton.icon(
                onPressed: () => onPick(ImageSource.camera),
                icon: const Icon(Icons.videocam),
                label: const Text('Record Video'),
                style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 16)),
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: 200,
              child: OutlinedButton.icon(
                onPressed: () => onPick(ImageSource.gallery),
                icon: const Icon(Icons.folder_open),
                label: const Text('Choose File'),
                style: OutlinedButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 16)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SavingOverlay extends StatelessWidget {
  const _SavingOverlay({required this.saving});
  final bool saving;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (saving) ...[
            const CircularProgressIndicator(),
            const SizedBox(height: 24),
            Text('Saving calibration...', style: theme.textTheme.titleMedium),
          ] else ...[
            Icon(Icons.check_circle, size: 64, color: theme.colorScheme.primary),
            const SizedBox(height: 16),
            Text('Calibration Complete', style: theme.textTheme.titleMedium),
          ],
        ],
      ),
    );
  }
}
