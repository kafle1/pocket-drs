import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:image_picker/image_picker.dart';

import 'camera_record_screen.dart'
  if (dart.library.html) 'camera_record_screen_web_stub.dart';
import 'review_screen.dart';
import 'settings_screen.dart';
import '../models/video_source.dart';
import '../utils/analysis_logger.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _picker = ImagePicker();
  bool _busy = false;

  bool get _supportsRecording {
    // Camera recording may work on some web builds, but reliability varies.
    // Keep it enabled only on mobile for now.
    if (kIsWeb) return false;
    return defaultTargetPlatform == TargetPlatform.android ||
        defaultTargetPlatform == TargetPlatform.iOS;
  }

  Future<void> _openReview(XFile xfile, VideoSource source) async {
    if (!mounted) return;
    final navigator = Navigator.of(context);
    await AnalysisLogger.instance.logAndPrint('home openReview source=${source.wireValue} path=${xfile.path}');
    if (!mounted) return;
    await navigator.push(
      MaterialPageRoute(builder: (_) => ReviewScreen(videoFile: xfile, videoSource: source)),
    );
  }

  Future<void> _recordVideo() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await AnalysisLogger.instance.logAndPrint('home recordVideo start');
      if (!mounted) return;
      final navigator = Navigator.of(context);
      final file = await navigator.push<XFile?>(
        MaterialPageRoute(builder: (_) => const CameraRecordScreen()),
      );
      if (!mounted) return;
      if (file != null) {
        await _openReview(file, VideoSource.record);
      } else {
        await AnalysisLogger.instance.logAndPrint('home recordVideo cancelled');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _importVideo() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await AnalysisLogger.instance.logAndPrint('home importVideo start');
      final picked = await _picker.pickVideo(source: ImageSource.gallery);
      if (picked == null) return;
      await _openReview(picked, VideoSource.import);
    } catch (e) {
      await AnalysisLogger.instance.logAndPrint('home importVideo failed: $e');
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Failed to import video: ${e.toString().replaceAll(RegExp(r'^\w+Error: '), '')}')),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('PocketDRS'),
        backgroundColor: theme.colorScheme.surface,
        actions: [
          IconButton(
            tooltip: 'Settings',
            onPressed: _busy
                ? null
                : () {
                    Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => const SettingsScreen()),
                    );
                  },
            icon: const Icon(Icons.settings),
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Import a delivery clip, then select the delivery segment (ball release → impact).',
                style: theme.textTheme.bodyLarge,
              ),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: (!_supportsRecording || _busy) ? null : _recordVideo,
                icon: const Icon(Icons.videocam),
                label: const Text('Record video'),
              ),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: _busy ? null : _importVideo,
                icon: const Icon(Icons.video_library),
                label: const Text('Import video'),
              ),
              if (kIsWeb) ...[
                const SizedBox(height: 12),
                Text(
                  'Web tip: set Server URL to http://localhost:8000 in Settings (and start the backend with make dev-web).',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
              const SizedBox(height: 16),
              if (_busy)
                const Center(
                  child: Padding(
                    padding: EdgeInsets.only(top: 8),
                    child: CircularProgressIndicator(),
                  ),
                ),
              const Spacer(),
              Text(
                'Setup assumptions (for real-game reliability): tripod + daylight + fixed umpire-style camera angle.',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
