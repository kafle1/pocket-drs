import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../utils/format.dart';
import 'analysis_screen.dart';

class ReviewScreen extends StatefulWidget {
  const ReviewScreen({super.key, required this.videoPath});

  final String videoPath;

  @override
  State<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends State<ReviewScreen> {
  VideoPlayerController? _controller;
  Duration _duration = Duration.zero;
  RangeValues _range = const RangeValues(0, 0);
  String? _error;

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
      if (kIsWeb) {
        throw UnsupportedError(
          'Video review is not supported on Web/Desktop. Run the app on Android/iOS.',
        );
      }

      final c = VideoPlayerController.file(File(widget.videoPath));
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
      if (!mounted) return;
      setState(() => _error = e.toString());
    }
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
                : Column(
                    children: [
                      AspectRatio(
                        aspectRatio: c.value.aspectRatio,
                        child: VideoPlayer(c),
                      ),
                      Padding(
                        padding: const EdgeInsets.all(12),
                        child: Row(
                          children: [
                            IconButton(
                              tooltip: c.value.isPlaying ? 'Pause' : 'Play',
                              onPressed: () {
                                setState(() {
                                  c.value.isPlaying ? c.pause() : c.play();
                                });
                              },
                              icon: Icon(c.value.isPlaying ? Icons.pause : Icons.play_arrow),
                            ),
                            Expanded(
                              child: VideoProgressIndicator(
                                c,
                                allowScrubbing: true,
                                colors: VideoProgressColors(
                                  playedColor: theme.colorScheme.primary,
                                  bufferedColor: theme.colorScheme.surfaceContainerHighest,
                                  backgroundColor: theme.colorScheme.surfaceContainer,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Text(
                              'Select delivery segment (release → impact)',
                              style: theme.textTheme.titleMedium,
                            ),
                            const SizedBox(height: 8),
                            RangeSlider(
                              min: 0,
                              max: maxMs,
                              divisions: _duration.inMilliseconds > 0
                                  ? _duration.inMilliseconds
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
                              onPressed: () {
                                final start = Duration(milliseconds: startMs.round());
                                final end = Duration(milliseconds: endMs.round());
                                Navigator.of(context).push(
                                  MaterialPageRoute(
                                    builder: (_) => AnalysisScreen(
                                      videoPath: widget.videoPath,
                                      start: start,
                                      end: end,
                                    ),
                                  ),
                                );
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
                      const SizedBox(height: 8),
                    ],
                  ),
      ),
    );
  }
}
