import 'dart:io';
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

enum _Step { video, frame, pitch, stumps, ball, done }

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
  List<Offset>? _stumpMarkers;
  XFile? _ballImage;
  bool _saving = false;

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
      _step = _Step.stumps;
    });
  }

  void _onStumpsComplete(List<Offset> markers) {
    setState(() {
      _stumpMarkers = markers;
      _step = _Step.ball;
    });
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
      final stumpPts = _stumpMarkers?.map((p) => Offset(p.dx * w, p.dy * h)).toList();

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
          stumpPointsNorm: _stumpMarkers == null ? null : List.unmodifiable(_stumpMarkers!),
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
        case _Step.stumps:
          _step = _Step.pitch;
          _pitchCorners = null;
        case _Step.ball:
          _step = _Step.stumps;
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
  static const _steps = ['Video', 'Frame', 'Pitch', 'Stumps', 'Ball'];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Theme.of(context).colorScheme.surface,
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
                preferredSize: const Size.fromHeight(40),
                child: _StepIndicator(current: _stepIndex, steps: _steps),
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
                onComplete: _onPitchComplete,
              );
      case _Step.stumps:
        return _framePath == null
            ? const SizedBox()
            : ImageMarker(
                key: const ValueKey('stump_markers'),
                imagePath: _framePath!,
                maxMarkers: 4,
                title: 'Mark Stumps',
                subtitle: 'Tap the base and top of both stumps',
                markerLabels: const ['Near Base', 'Near Top', 'Far Base', 'Far Top'],
                onComplete: _onStumpsComplete,
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
