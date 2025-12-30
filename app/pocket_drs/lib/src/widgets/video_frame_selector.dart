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
  VideoPlayerController? _controller;
  bool _ready = false;

  bool _selecting = false;

  Timer? _seekDebounce;
  bool _scrubbing = false;
  double? _scrubValueMs;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    final controller = VideoPlayerController.file(File(widget.videoPath));
    _controller = controller;
    try {
      await controller.initialize();
      controller.addListener(_onUpdate);
      if (mounted) setState(() => _ready = true);
    } catch (e) {
      try {
        await controller.dispose();
      } catch (_) {}
      if (_controller == controller) {
        _controller = null;
      }
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
    final controller = _controller;
    if (controller != null) {
      controller.removeListener(_onUpdate);
      controller.dispose();
      _controller = null;
    }
    super.dispose();
  }

  void _scheduleSeekMs(int ms) {
    _seekDebounce?.cancel();
    _seekDebounce = Timer(const Duration(milliseconds: 200), () {
      if (!mounted) return;
      _controller?.seekTo(Duration(milliseconds: ms));
    });
  }

  void _stepBack() {
    final controller = _controller;
    if (controller == null) return;
    final pos = controller.value.position - const Duration(milliseconds: 100);
    controller.seekTo(pos.isNegative ? Duration.zero : pos);
  }

  void _stepForward() {
    final controller = _controller;
    if (controller == null) return;
    final pos = controller.value.position + const Duration(milliseconds: 100);
    final max = controller.value.duration;
    controller.seekTo(pos > max ? max : pos);
  }

  Future<void> _select() async {
    if (_selecting) return;
    final controller = _controller;
    if (controller == null) return;

    setState(() => _selecting = true);
    try {
      await controller.pause();

      // Critical: release playback decoder BEFORE triggering frame extraction.
      // Android's MediaCodec/ImageReader pools can be exhausted if video playback
      // and thumbnail extraction overlap.
      controller.removeListener(_onUpdate);
      await controller.dispose();
      if (_controller == controller) {
        _controller = null;
      }

      // Give the platform a brief window to recycle ImageReader buffers before
      // the thumbnail extractor spins up.
      await Future<void>.delayed(const Duration(milliseconds: 200));

      widget.onFrameSelected(controller.value.position);
    } finally {
      if (mounted) setState(() => _selecting = false);
    }
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

    final controller = _controller;
    if (controller == null) return const Center(child: CircularProgressIndicator());

    final theme = Theme.of(context);
    final pos = controller.value.position;
    final dur = controller.value.duration;
    final playing = controller.value.isPlaying;

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
                aspectRatio: controller.value.aspectRatio,
                child: VideoPlayer(controller),
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
                            if (controller.value.isPlaying) {
                              controller.pause();
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
                            controller.seekTo(Duration(milliseconds: v.toInt()));
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
                      onPressed: _selecting ? null : () => playing ? controller.pause() : controller.play(),
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
                    onPressed: _selecting ? null : _select,
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
