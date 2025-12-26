import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:video_player/video_player.dart';

import '../analysis/calibration_config.dart';
import '../utils/format.dart';
import '../utils/calibration_store.dart';
import '../utils/route_interactive.dart';
import '../utils/video_controller_factory.dart';
import '../widgets/review_layout.dart';
import '../models/video_source.dart';
import '../utils/analysis_logger.dart';
import 'analysis_screen.dart';
import 'calibration_screen.dart';
import 'pitch_calibration_screen.dart';

class ReviewScreen extends StatefulWidget {
  const ReviewScreen({super.key, required this.videoFile, required this.videoSource});

  final XFile videoFile;
  final VideoSource videoSource;

  @override
  State<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends State<ReviewScreen> {
  VideoPlayerController? _controller;
  Duration _duration = Duration.zero;
  RangeValues _range = const RangeValues(0, 0);
  String? _error;
  bool _navigating = false;
  final _calibrationStore = CalibrationStore();

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    setState(() {
      _error = null;
    });

    try {
      await AnalysisLogger.instance.logAndPrint(
        'review init path=${widget.videoFile.path} source=${widget.videoSource.wireValue}',
      );

      final c = createVideoPlayerController(widget.videoFile.path);
      await c.initialize();
      final d = c.value.duration;

      if (!mounted) return;
      setState(() {
        _controller?.dispose();
        _controller = c;
        _duration = d;
        _range = RangeValues(0, d.inMilliseconds.toDouble());
      });
    } catch (e) {
      await AnalysisLogger.instance.logAndPrint('review init failed: $e');
      if (!mounted) return;
      setState(() => _error = e.toString());
    }
  }

  Future<void> _releaseController() async {
    final c = _controller;
    if (c == null) return;
    try {
      await c.pause();
    } catch (_) {}
    await c.dispose();
    _controller = null;
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  Future<void> _seekToMs(int ms) async {
    final c = _controller;
    if (c == null) return;
    await c.seekTo(Duration(milliseconds: ms));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final c = _controller;

    final maxMs = _duration.inMilliseconds.toDouble().clamp(1.0, double.infinity).toDouble();
    final startMs = _range.start.clamp(0.0, maxMs).toDouble();
    final endMs = _range.end.clamp(0.0, maxMs).toDouble();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Review clip'),
        actions: [
          IconButton(
            tooltip: 'Reload',
            onPressed: _init,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        child: _error != null
            ? Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text('Video error', style: theme.textTheme.titleLarge),
                    const SizedBox(height: 8),
                    Text(_error!),
                    const SizedBox(height: 16),
                    FilledButton(onPressed: _init, child: const Text('Try again')),
                  ],
                ),
              )
            : c == null || !c.value.isInitialized
                ? const Center(child: CircularProgressIndicator())
                : ReviewLayout(
                    video: AspectRatio(
                      aspectRatio: c.value.aspectRatio,
                      child: VideoPlayer(c),
                    ),
                    controls: Padding(
                      padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Row(
                            children: [
                              IconButton(
                                tooltip: c.value.isPlaying ? 'Pause' : 'Play',
                                onPressed: () async {
                                  if (c.value.isPlaying) {
                                    await c.pause();
                                  } else {
                                    await c.play();
                                  }
                                  if (mounted) setState(() {});
                                },
                                icon: Icon(
                                  c.value.isPlaying ? Icons.pause : Icons.play_arrow,
                                ),
                              ),
                              Expanded(
                                child: VideoProgressIndicator(
                                  c,
                                  allowScrubbing: true,
                                  colors: VideoProgressColors(
                                    playedColor: theme.colorScheme.primary,
                                    bufferedColor:
                                        theme.colorScheme.surfaceContainerHighest,
                                    backgroundColor:
                                        theme.colorScheme.surfaceContainer,
                                  ),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 12),
                          Text(
                            'Select delivery segment (release → impact)',
                            style: theme.textTheme.titleMedium,
                          ),
                          const SizedBox(height: 8),
                          RangeSlider(
                            min: 0,
                            max: maxMs,
                            divisions: _duration.inMilliseconds > 0
                                ? (_duration.inMilliseconds / 100).ceil().clamp(10, 500)
                                : null,
                            values: RangeValues(startMs, endMs),
                            labels: RangeLabels(
                              formatDuration(Duration(milliseconds: startMs.round())),
                              formatDuration(Duration(milliseconds: endMs.round())),
                            ),
                            onChanged: (v) {
                              final safe = v.start <= v.end
                                  ? v
                                  : RangeValues(v.end, v.start);
                              setState(() => _range = safe);
                            },
                            onChangeEnd: (v) => _seekToMs(v.start.round()),
                          ),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Text(
                                'Start: ${formatDuration(Duration(milliseconds: startMs.round()))}',
                              ),
                              Text(
                                'End: ${formatDuration(Duration(milliseconds: endMs.round()))}',
                              ),
                            ],
                          ),
                          const SizedBox(height: 12),
                          FilledButton.icon(
                            onPressed: _navigating
                                ? null
                                : () async {
                                    setState(() => _navigating = true);
                                    try {
                                      if (!context.mounted) return;
                                      await waitForRouteInteractive(context);
                                      if (!context.mounted) return;
                                      final start = Duration(milliseconds: startMs.round());
                                      final end = Duration(milliseconds: endMs.round());
                                      await _releaseController();
                                      if (!context.mounted) return;

                                      final initialCalibration =
                                          await _calibrationStore.loadOrDefault();
                                      if (!context.mounted) return;
                                      final calibration =
                                          await Navigator.of(context).push<CalibrationConfig?>(
                                        MaterialPageRoute(
                                          builder: (_) => CalibrationScreen(
                                            initial: initialCalibration,
                                          ),
                                        ),
                                      );
                                      if (!context.mounted) return;
                                      if (calibration == null) {
                                        return;
                                      }

                                      var finalCalibration = calibration;

                                      // Pitch-plane tap calibration (optional for now).
                                      // This enables mapping pixels -> meters for Hawkeye/LBW style outputs.
                                      if (finalCalibration.pitchCalibration == null) {
                                        await waitForRouteInteractive(context);
                                        if (!context.mounted) return;
                                        final pitchCalibrated =
                                            await Navigator.of(context).push<
                                                CalibrationConfig?>(
                                          MaterialPageRoute(
                                            builder: (_) => PitchCalibrationScreen(
                                              videoPath: widget.videoFile.path,
                                              frameTimeMs: startMs.round(),
                                              config: finalCalibration,
                                            ),
                                          ),
                                        );
                                        if (!context.mounted) return;
                                        if (pitchCalibrated != null) {
                                          finalCalibration = pitchCalibrated;
                                        }
                                      }

                                      await Navigator.of(context).push(
                                        MaterialPageRoute(
                                          builder: (_) => AnalysisScreen(
                                            videoFile: widget.videoFile,
                                            start: start,
                                            end: end,
                                            calibration: finalCalibration,
                                            videoSource: widget.videoSource,
                                          ),
                                        ),
                                      );
                                      if (!context.mounted) return;
                                      await _init();
                                    } finally {
                                      if (mounted) {
                                        setState(() => _navigating = false);
                                      }
                                    }
                                  },
                            icon: const Icon(Icons.check),
                            label: const Text('Use this segment'),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            'Tip: keep the segment short (1–2 seconds). It makes tracking + calibration much more reliable.',
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.colorScheme.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
      ),
    );
  }
}
