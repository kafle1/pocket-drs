import 'dart:io';
import 'dart:math' as math;
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';

import '../analysis/calibration_config.dart';
import '../analysis/frame_decoder.dart';
import '../analysis/pitch_calibration.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../utils/pitch_store.dart';
import '../widgets/drs_button.dart';
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
    } catch (_) {
      _showError('Failed to get video');
    }
  }

  Future<void> _onFrameSelected(Duration timestamp) async {
    if (_video == null) return;
    try {
      final tempDir = await getTemporaryDirectory();
      final framePath = '${tempDir.path}/cal_${timestamp.inMilliseconds}.jpg';
      final bytes = await decodeFrameJpeg(
        videoPath: _video!.path,
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
    } catch (_) {
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
    final dStriker = _distPointToLine(base, corners[0], corners[1]);
    final dBowler = _distPointToLine(base, corners[3], corners[2]);
    return dStriker <= dBowler;
  }

  bool _validateStumpPair(List<Offset> pair, {required String endName}) {
    if (pair.length != 2) {
      _showError('Mark both base and top for $endName end');
      return false;
    }
    if (pair[1].dy >= pair[0].dy) {
      _showError('For $endName end: tap base first, then top');
      return false;
    }
    return true;
  }

  Future<void> _onStrikerStumpsComplete(List<Offset> markers) async {
    if (!_validateStumpPair(markers, endName: 'striker')) return;
    if (!_looksLikeStrikerEnd(markers[0])) {
      final swap = await _confirmSwapEnds(
        title: 'Looks like bowler end',
        message: 'The base you tapped is closer to the bowler-end line. Treat as bowler stumps?',
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
    if (_looksLikeStrikerEnd(markers[0])) {
      final swap = await _confirmSwapEnds(
        title: 'Looks like striker end',
        message: 'The base you tapped is closer to the striker-end line. Treat as striker stumps?',
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
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('KEEP')),
          FilledButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('SWAP')),
        ],
      ),
    );
    return res ?? false;
  }

  Future<void> _pickBallImage(ImageSource source) async {
    try {
      final img = await _picker.pickImage(source: source, imageQuality: 90);
      if (!mounted || img == null) return;
      setState(() => _ballImage = img);
    } catch (_) {
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
      if (!await pitchDir.exists()) await pitchDir.create(recursive: true);
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

      try {
        PitchCalibration(imagePoints: pitchPts).validateImageQuad();
      } catch (e) {
        if (mounted) {
          setState(() => _saving = false);
          _showError(e is StateError ? e.message : 'Invalid pitch calibration');
        }
        return;
      }

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
        await Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => PostCalibration3DScreen(
              pitchId: widget.pitchId,
              pitchName: widget.pitchName,
              calibration: calibration.pitchCalibration!,
            ),
          ),
        );
        if (mounted) Navigator.of(context).pop(true);
      }
    } catch (_) {
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
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  static const _stepLabels = ['VIDEO', 'FRAME', 'PITCH', 'STRIKER', 'BOWLER', 'REVIEW', 'BALL'];

  String? get _stepHint => switch (_step) {
        _Step.pitch => 'Tap pitch corners clockwise starting at striker end.',
        _Step.stumpsStriker || _Step.stumpsBowler => 'Tap base first, then top. Pinch to zoom.',
        _Step.review => 'Zoom in and confirm. Use Edit to fix anything.',
        _ => null,
      };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final hint = _stepHint;
    final hasHint = hint != null;

    return Scaffold(
      appBar: _step == _Step.done
          ? null
          : PreferredSize(
              preferredSize: Size.fromHeight(hasHint ? 132 : 100),
              child: SafeArea(
                bottom: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(
                    AppSpacing.sm,
                    AppSpacing.xs,
                    AppSpacing.lg,
                    AppSpacing.md,
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          IconButton(
                            onPressed: _goBack,
                            icon: const Icon(Icons.arrow_back, size: 20),
                          ),
                          const SizedBox(width: AppSpacing.xs),
                          Text(
                            'STEP ${(_step.index + 1).toString().padLeft(2, '0')} / 07',
                            style: theme.textTheme.labelSmall?.copyWith(
                              color: scheme.onSurfaceVariant,
                            ),
                          ),
                          const Spacer(),
                          Text(
                            widget.pitchName.toUpperCase(),
                            style: theme.textTheme.labelSmall?.copyWith(
                              color: scheme.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Padding(
                        padding: const EdgeInsets.only(left: AppSpacing.md),
                        child: Text(
                          _stepLabels[_step.index].toLowerCase().replaceFirstMapped(
                                RegExp(r'^.'),
                                (m) => m.group(0)!.toUpperCase(),
                              ),
                          style: theme.textTheme.headlineSmall,
                        ),
                      ),
                      const SizedBox(height: AppSpacing.md),
                      _StepBar(current: _step.index, total: _stepLabels.length),
                      if (hasHint) ...[
                        const SizedBox(height: AppSpacing.md),
                        Padding(
                          padding: const EdgeInsets.only(left: AppSpacing.md),
                          child: Text(
                            hint,
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: scheme.onSurfaceVariant,
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
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
                subtitle: 'Tap corners clockwise from striker end',
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
                subtitle: 'Tap base, then top',
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
                subtitle: 'Tap base, then top',
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
    final outline = <Offset>[corners[0], corners[1], corners[2], corners[3], corners[0]];
    final strikerLine = <Offset>[corners[0], corners[1]];
    final bowlerLine = <Offset>[corners[3], corners[2]];
    return <List<Offset>>[outline, strikerLine, bowlerLine];
  }
}

class _StepBar extends StatelessWidget {
  const _StepBar({required this.current, required this.total});
  final int current;
  final int total;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return SizedBox(
      height: 4,
      child: Row(
        children: List.generate(total, (i) {
          final done = i <= current;
          return Expanded(
            child: Container(
              margin: EdgeInsets.only(right: i == total - 1 ? 0 : 2),
              color: done ? AppColors.signalRed : scheme.surfaceContainerHigh,
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
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Spacer(),
          Text(
            '01.',
            style: AppTypography.mono(theme.textTheme.displayMedium)?.copyWith(
              color: AppColors.signalRed,
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          Text('Calibration video.', style: theme.textTheme.headlineMedium),
          const SizedBox(height: AppSpacing.md),
          Text(
            'Record a still video showing the full pitch with both sets of stumps visible.',
            style: theme.textTheme.bodyLarge?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          const Spacer(),
          DrsButton(
            label: 'RECORD VIDEO',
            icon: Icons.videocam_outlined,
            onPressed: () => onPick(ImageSource.camera),
          ),
          const SizedBox(height: AppSpacing.md),
          DrsButton(
            label: 'CHOOSE FILE',
            icon: Icons.folder_open,
            style: DrsButtonStyle.secondary,
            onPressed: () => onPick(ImageSource.gallery),
          ),
          const SizedBox(height: AppSpacing.xl),
        ],
      ),
    );
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
    final scale = (viewport.width / s.width).clamp(0.05, 10.0);
    final scale2 = (viewport.height / s.height).clamp(0.05, 10.0);
    final k = scale < scale2 ? scale : scale2;
    final dx = (viewport.width - s.width * k) / 2.0;
    final dy = (viewport.height - s.height * k) / 2.0;
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
    final scheme = Theme.of(context).colorScheme;
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
                      color: AppColors.inkBlack,
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
          decoration: BoxDecoration(
            color: scheme.surface,
            border: Border(top: BorderSide(color: scheme.outline, width: 1)),
          ),
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.xl,
                AppSpacing.lg,
                AppSpacing.xl,
                AppSpacing.lg,
              ),
              child: Column(
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: DrsButton(
                          label: 'PITCH',
                          style: DrsButtonStyle.secondary,
                          onPressed: widget.onEditPitch,
                        ),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: DrsButton(
                          label: 'STRIKER',
                          style: DrsButtonStyle.secondary,
                          onPressed: widget.onEditStriker,
                        ),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: DrsButton(
                          label: 'BOWLER',
                          style: DrsButtonStyle.secondary,
                          onPressed: widget.onEditBowler,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.md),
                  DrsButton(
                    label: 'CONTINUE',
                    icon: Icons.arrow_forward,
                    onPressed: widget.onContinue,
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

class _CalibrationReviewPainter extends CustomPainter {
  _CalibrationReviewPainter({
    required this.pitchCorners,
    required this.strikerStumps,
    required this.bowlerStumps,
  });

  final List<Offset> pitchCorners;
  final List<Offset>? strikerStumps;
  final List<Offset>? bowlerStumps;

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

    canvas.drawPath(outline, Paint()..color = AppColors.signalRed.withValues(alpha: 0.08));
    canvas.drawPath(
      outline,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..color = AppColors.signalRed,
    );

    void drawStumps(List<Offset>? pair, Color c) {
      if (pair == null || pair.length != 2) return;
      final b = Offset(pair[0].dx * size.width, pair[0].dy * size.height);
      final t = Offset(pair[1].dx * size.width, pair[1].dy * size.height);
      final p = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.5
        ..color = c;
      canvas.drawLine(b, t, p);
      canvas.drawCircle(b, 7, Paint()..color = c.withValues(alpha: 0.3));
      canvas.drawCircle(b, 4, Paint()..color = c);
      canvas.drawCircle(t, 7, Paint()..color = c.withValues(alpha: 0.3));
      canvas.drawCircle(t, 4, Paint()..color = c);
    }

    drawStumps(strikerStumps, AppColors.pitchGreen);
    drawStumps(bowlerStumps, AppColors.caution);
  }

  @override
  bool shouldRepaint(_CalibrationReviewPainter old) {
    return old.pitchCorners != pitchCorners ||
        old.strikerStumps != strikerStumps ||
        old.bowlerStumps != bowlerStumps;
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
    final scheme = theme.colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: AppSpacing.lg),
          Text(
            'Ball reference photo.',
            style: theme.textTheme.headlineSmall,
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            'Optional. A clear photo of the match ball improves detection.',
            style: theme.textTheme.bodyMedium?.copyWith(color: scheme.onSurfaceVariant),
          ),
          const SizedBox(height: AppSpacing.xl),
          Expanded(
            child: Container(
              decoration: BoxDecoration(
                color: scheme.surfaceContainer,
                border: Border.all(color: scheme.outline, width: 1),
              ),
              clipBehavior: Clip.antiAlias,
              child: ballImage == null
                  ? Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.sports_baseball_outlined, size: 28, color: scheme.onSurfaceVariant),
                          const SizedBox(height: AppSpacing.md),
                          Text(
                            'NO BALL PHOTO',
                            style: theme.textTheme.labelSmall?.copyWith(
                              color: scheme.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                    )
                  : Image.file(File(ballImage!.path), fit: BoxFit.contain),
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          Row(
            children: [
              Expanded(
                child: DrsButton(
                  label: 'CAMERA',
                  style: DrsButtonStyle.secondary,
                  icon: Icons.photo_camera_outlined,
                  onPressed: onPickCamera,
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: DrsButton(
                  label: 'GALLERY',
                  style: DrsButtonStyle.secondary,
                  icon: Icons.photo_outlined,
                  onPressed: onPickGallery,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          DrsButton(
            label: 'SAVE CALIBRATION',
            icon: Icons.check,
            onPressed: onContinue,
          ),
          const SizedBox(height: AppSpacing.xl),
        ],
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
            const SizedBox(
              width: 32,
              height: 32,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            const SizedBox(height: AppSpacing.lg),
            Text(
              'SAVING CALIBRATION',
              style: theme.textTheme.labelLarge?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ] else ...[
            Container(
              width: 56,
              height: 56,
              decoration: const BoxDecoration(
                color: AppColors.pitchGreen,
              ),
              child: const Icon(Icons.check, color: AppColors.inkBlack, size: 28),
            ),
            const SizedBox(height: AppSpacing.lg),
            Text(
              'CALIBRATION COMPLETE',
              style: theme.textTheme.labelLarge?.copyWith(color: AppColors.pitchGreen),
            ),
          ],
        ],
      ),
    );
  }
}
