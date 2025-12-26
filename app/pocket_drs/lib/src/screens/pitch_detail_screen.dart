import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../analysis/calibration_config.dart';
import '../models/pitch.dart';
import '../models/video_source.dart';
import '../utils/analysis_logger.dart';
import '../utils/pitch_store.dart';
import 'camera_record_screen.dart'
  if (dart.library.html) 'camera_record_screen_web_stub.dart';
import 'calibration_screen.dart';
import 'pitch_calibration_screen.dart';
import 'pitch_edit_screen.dart';
import 'review_screen.dart';

class PitchDetailScreen extends StatefulWidget {
  const PitchDetailScreen({
    super.key,
    required this.pitchId,
  });

  final String pitchId;

  @override
  State<PitchDetailScreen> createState() => _PitchDetailScreenState();
}

class _PitchDetailScreenState extends State<PitchDetailScreen> {
  final _store = PitchStore();
  final _picker = ImagePicker();

  bool _loading = true;
  bool _busy = false;
  String? _error;
  Pitch? _pitch;

  bool get _supportsRecording {
    if (kIsWeb) return false;
    return defaultTargetPlatform == TargetPlatform.android ||
        defaultTargetPlatform == TargetPlatform.iOS;
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final pitch = await _store.loadById(widget.pitchId);
      if (!mounted) return;
      setState(() {
        _pitch = pitch;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _editName() async {
    final pitch = _pitch;
    if (pitch == null) return;

    final name = await Navigator.of(context).push<String?>(
      MaterialPageRoute(builder: (_) => PitchEditScreen(initial: pitch)),
    );
    if (!mounted || name == null) return;

    final next = pitch.copyWith(name: name, updatedAt: DateTime.now());
    await _store.update(next);
    if (mounted) await _load();
  }

  Future<void> _delete() async {
    final pitch = _pitch;
    if (pitch == null) return;

    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete pitch?'),
        content: Text('This will remove “${pitch.name}” and its saved calibration.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
              foregroundColor: Theme.of(context).colorScheme.onError,
            ),
            child: const Text('Delete'),
          ),
        ],
      ),
    );

    if (!mounted || ok != true) return;
    await _store.delete(pitch.id);
    if (!mounted) return;
    Navigator.of(context).pop();
  }

  Future<XFile?> _pickCalibrationClip() async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (context) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('Calibration clip', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                Text(
                  'Record or choose a short clip where both stumps and the pitch edges are clearly visible.',
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: _supportsRecording ? () => Navigator.of(context).pop('record') : null,
                  icon: const Icon(Icons.videocam),
                  label: const Text('Record calibration clip'),
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: () => Navigator.of(context).pop('import'),
                  icon: const Icon(Icons.video_library),
                  label: const Text('Import calibration clip'),
                ),
                if (kIsWeb) ...[
                  const SizedBox(height: 12),
                  Text(
                    'Note: camera recording is disabled on Web builds. Use Import instead.',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                  ),
                ],
              ],
            ),
          ),
        );
      },
    );

    if (!mounted || choice == null) return null;

    if (choice == 'record') {
      final file = await Navigator.of(context).push<XFile?>(
        MaterialPageRoute(builder: (_) => const CameraRecordScreen()),
      );
      return file;
    }

    if (choice == 'import') {
      return _picker.pickVideo(source: ImageSource.gallery);
    }

    return null;
  }

  Future<void> _calibrate() async {
    final pitch = _pitch;
    if (pitch == null || _busy) return;

    setState(() {
      _busy = true;
      _error = null;
    });

    try {
      await AnalysisLogger.instance.logAndPrint('pitch calibrate start id=${pitch.id}');

      final initial = pitch.calibration ?? PitchStore.defaultCalibration();

      final cfg = await Navigator.of(context).push<CalibrationConfig?>(
        MaterialPageRoute(builder: (_) => CalibrationScreen(initial: initial)),
      );
      if (!mounted || cfg == null) return;

      final clip = await _pickCalibrationClip();
      if (!mounted || clip == null) return;

      final tapped = await Navigator.of(context).push<CalibrationConfig?>(
        MaterialPageRoute(
          builder: (_) => PitchCalibrationScreen(
            videoPath: clip.path,
            frameTimeMs: 200,
            config: cfg,
          ),
        ),
      );

      if (!mounted) return;
      if (tapped == null || tapped.pitchCalibration == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Pitch calibration is required to continue')),
        );
        return;
      }

      final next = pitch.copyWith(
        calibration: tapped,
        updatedAt: DateTime.now(),
      );
      await _store.update(next);

      if (mounted) {
        await _load();
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Pitch calibrated and saved')),
        );
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _openReview({required XFile file, required VideoSource source}) async {
    final pitch = _pitch;
    if (pitch == null) return;

    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ReviewScreen(
          pitchId: pitch.id,
          videoFile: file,
          videoSource: source,
        ),
      ),
    );
  }

  Future<void> _recordDelivery() async {
    final pitch = _pitch;
    if (pitch == null || _busy) return;
    if (!pitch.isCalibrated) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Calibrate this pitch before recording deliveries')),
      );
      return;
    }

    setState(() => _busy = true);
    try {
      final file = await Navigator.of(context).push<XFile?>(
        MaterialPageRoute(builder: (_) => const CameraRecordScreen()),
      );
      if (!mounted || file == null) return;
      await _openReview(file: file, source: VideoSource.record);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _importDelivery() async {
    final pitch = _pitch;
    if (pitch == null || _busy) return;
    if (!pitch.isCalibrated) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Calibrate this pitch before importing deliveries')),
      );
      return;
    }

    setState(() => _busy = true);
    try {
      final picked = await _picker.pickVideo(source: ImageSource.gallery);
      if (!mounted || picked == null) return;
      await _openReview(file: picked, source: VideoSource.import);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to import video: $e')),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    final pitch = _pitch;
    final calibrated = pitch?.isCalibrated ?? false;

    return Scaffold(
      appBar: AppBar(
        title: Text(pitch?.name ?? 'Pitch'),
        actions: [
          IconButton(
            tooltip: 'Edit name',
            onPressed: (_loading || pitch == null) ? null : _editName,
            icon: const Icon(Icons.edit),
          ),
          IconButton(
            tooltip: 'Delete',
            onPressed: (_loading || pitch == null) ? null : _delete,
            icon: const Icon(Icons.delete_outline),
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
                        Text('Pitch error', style: theme.textTheme.titleLarge),
                        const SizedBox(height: 8),
                        Text(_error!),
                        const SizedBox(height: 16),
                        FilledButton(onPressed: _load, child: const Text('Try again')),
                      ],
                    ),
                  )
                : pitch == null
                    ? Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Text('Pitch not found', style: theme.textTheme.titleLarge),
                            const SizedBox(height: 8),
                            Text(
                              'It may have been deleted on this device.',
                              style: theme.textTheme.bodyMedium?.copyWith(
                                color: theme.colorScheme.onSurfaceVariant,
                              ),
                            ),
                          ],
                        ),
                      )
                    : ListView(
                        padding: const EdgeInsets.all(16),
                        children: [
                          Card(
                            child: Padding(
                              padding: const EdgeInsets.all(16),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.stretch,
                                children: [
                                  Row(
                                    children: [
                                      Container(
                                        width: 10,
                                        height: 10,
                                        decoration: BoxDecoration(
                                          color: calibrated
                                              ? theme.colorScheme.tertiary
                                              : theme.colorScheme.error,
                                          shape: BoxShape.circle,
                                        ),
                                      ),
                                      const SizedBox(width: 8),
                                      Text(
                                        calibrated ? 'Calibrated' : 'Needs calibration',
                                        style: theme.textTheme.titleSmall,
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 12),
                                  Text(
                                    'Workflow: calibrate once → record/import deliveries → analyze.',
                                    style: theme.textTheme.bodyMedium?.copyWith(
                                      color: theme.colorScheme.onSurfaceVariant,
                                    ),
                                  ),
                                  const SizedBox(height: 16),
                                  FilledButton.icon(
                                    onPressed: _busy ? null : _calibrate,
                                    icon: const Icon(Icons.tune),
                                    label: Text(calibrated ? 'Recalibrate' : 'Calibrate pitch'),
                                  ),
                                ],
                              ),
                            ),
                          ),
                          const SizedBox(height: 16),
                          Text('Deliveries', style: theme.textTheme.titleMedium),
                          const SizedBox(height: 12),
                          FilledButton.icon(
                            onPressed: (!_supportsRecording || _busy || !calibrated) ? null : _recordDelivery,
                            icon: const Icon(Icons.videocam),
                            label: const Text('Record delivery'),
                          ),
                          const SizedBox(height: 12),
                          OutlinedButton.icon(
                            onPressed: (_busy || !calibrated) ? null : _importDelivery,
                            icon: const Icon(Icons.video_library),
                            label: const Text('Import delivery'),
                          ),
                          if (!calibrated) ...[
                            const SizedBox(height: 12),
                            Text(
                              'Calibration is required before you can record or import deliveries for this pitch.',
                              style: theme.textTheme.bodySmall?.copyWith(
                                color: theme.colorScheme.onSurfaceVariant,
                              ),
                            ),
                          ],
                        ],
                      ),
      ),
    );
  }
}
