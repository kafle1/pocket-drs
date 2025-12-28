import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

class VideoFrameSelector extends StatefulWidget {
  const VideoFrameSelector({
    super.key,
    required this.videoPath,
    required this.onFrameSelected,
  });

  final String videoPath;
  final void Function(Duration timestamp) onFrameSelected;

  @override
  State<VideoFrameSelector> createState() => _VideoFrameSelectorState();
}

class _VideoFrameSelectorState extends State<VideoFrameSelector> {
  late VideoPlayerController _controller;
  bool _ready = false;

  Timer? _seekDebounce;
  bool _scrubbing = false;
  double? _scrubValueMs;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    _controller = VideoPlayerController.file(File(widget.videoPath));
    try {
      await _controller.initialize();
      _controller.addListener(_onUpdate);
      if (mounted) setState(() => _ready = true);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to load video'), behavior: SnackBarBehavior.floating),
        );
      }
    }
  }

  void _onUpdate() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _seekDebounce?.cancel();
    _controller.removeListener(_onUpdate);
    _controller.dispose();
    super.dispose();
  }

  void _scheduleSeekMs(int ms) {
    _seekDebounce?.cancel();
    _seekDebounce = Timer(const Duration(milliseconds: 200), () {
      if (!mounted) return;
      _controller.seekTo(Duration(milliseconds: ms));
    });
  }

  void _stepBack() {
    final pos = _controller.value.position - const Duration(milliseconds: 100);
    _controller.seekTo(pos.isNegative ? Duration.zero : pos);
  }

  void _stepForward() {
    final pos = _controller.value.position + const Duration(milliseconds: 100);
    final max = _controller.value.duration;
    _controller.seekTo(pos > max ? max : pos);
  }

  void _select() {
    _controller.pause();
    widget.onFrameSelected(_controller.value.position);
  }

  String _fmt(Duration d) {
    final m = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    final ms = (d.inMilliseconds.remainder(1000) ~/ 100).toString();
    return '$m:$s.$ms';
  }

  @override
  Widget build(BuildContext context) {
    if (!_ready) return const Center(child: CircularProgressIndicator());

    final theme = Theme.of(context);
    final pos = _controller.value.position;
    final dur = _controller.value.duration;
    final playing = _controller.value.isPlaying;

    final maxMs = dur.inMilliseconds <= 0 ? 1.0 : dur.inMilliseconds.toDouble();
    final sliderValueMs = (_scrubbing ? (_scrubValueMs ?? pos.inMilliseconds.toDouble()) : pos.inMilliseconds.toDouble())
      .clamp(0.0, maxMs)
      .toDouble();
    final shownPos = Duration(milliseconds: sliderValueMs.toInt());

    return Column(
      children: [
        // Video
        Expanded(
          child: Container(
            color: const Color(0xFF0A0A0A),
            child: Center(
              child: AspectRatio(
                aspectRatio: _controller.value.aspectRatio,
                child: VideoPlayer(_controller),
              ),
            ),
          ),
        ),
        // Controls
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: theme.colorScheme.surface,
            border: Border(top: BorderSide(color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3))),
          ),
          child: SafeArea(
            top: false,
            child: Column(
              children: [
                // Timeline
                Row(
                  children: [
                    Text(_fmt(shownPos), style: theme.textTheme.labelSmall),
                    const SizedBox(width: 12),
                    Expanded(
                      child: SliderTheme(
                        data: SliderTheme.of(context).copyWith(
                          trackHeight: 4,
                          thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 8),
                        ),
                        child: Slider(
                          value: sliderValueMs,
                          max: maxMs,
                          onChangeStart: (_) {
                            if (_controller.value.isPlaying) {
                              _controller.pause();
                            }
                            setState(() {
                              _scrubbing = true;
                              _scrubValueMs = sliderValueMs;
                            });
                          },
                          onChanged: (v) {
                            setState(() => _scrubValueMs = v);
                            _scheduleSeekMs(v.toInt());
                          },
                          onChangeEnd: (v) {
                            _seekDebounce?.cancel();
                            _controller.seekTo(Duration(milliseconds: v.toInt()));
                            setState(() {
                              _scrubbing = false;
                              _scrubValueMs = null;
                            });
                          },
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Text(_fmt(dur), style: theme.textTheme.labelSmall),
                  ],
                ),
                const SizedBox(height: 12),
                // Playback
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    _ControlButton(icon: Icons.skip_previous, onTap: _stepBack, label: '-0.1s'),
                    const SizedBox(width: 16),
                    FloatingActionButton.small(
                      onPressed: () => playing ? _controller.pause() : _controller.play(),
                      child: Icon(playing ? Icons.pause : Icons.play_arrow),
                    ),
                    const SizedBox(width: 16),
                    _ControlButton(icon: Icons.skip_next, onTap: _stepForward, label: '+0.1s'),
                  ],
                ),
                const SizedBox(height: 20),
                // Select
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: _select,
                    icon: const Icon(Icons.check_circle_outline),
                    label: const Text('Use This Frame'),
                    style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 14)),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _ControlButton extends StatelessWidget {
  const _ControlButton({required this.icon, required this.onTap, required this.label});
  final IconData icon;
  final VoidCallback onTap;
  final String label;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: theme.colorScheme.surfaceContainer,
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(
            children: [
              Icon(icon, size: 18),
              const SizedBox(width: 6),
              Text(label, style: theme.textTheme.labelMedium),
            ],
          ),
        ),
      ),
    );
  }
}
