import 'dart:async';
import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../utils/native_video_resources.dart';
import '../utils/video_controller_factory.dart';

class VideoFrameSelector extends StatefulWidget {
  const VideoFrameSelector({
    super.key,
    required this.videoPath,
    required this.onFrameSelected,
  });

  final String videoPath;
  // returns whether the frame was used; false leaves this widget's player usable again
  final Future<bool> Function(Duration timestamp) onFrameSelected;

  @override
  State<VideoFrameSelector> createState() => _VideoFrameSelectorState();
}

class _VideoFrameSelectorState extends State<VideoFrameSelector> {
  VideoPlayerController? _controller;
  bool _ready = false;
  bool _selecting = false;
  bool _failed = false;

  Timer? _seekDebounce;
  bool _scrubbing = false;
  double? _scrubValueMs;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    final controller = createVideoPlayerController(widget.videoPath);
    try {
      await runWithNativeVideoResources(() async {
        await coolDownNativeVideoResources(
          delay: const Duration(milliseconds: 350),
        );
        await controller.initialize();
      });
    } catch (_) {
      try {
        await controller.dispose();
      } catch (_) {}
      if (mounted) setState(() => _failed = true);
      return;
    }
    // left while it was loading, so dispose() never saw this controller
    if (!mounted) {
      await controller.dispose();
      return;
    }
    _controller = controller;
    controller.addListener(_onUpdate);
    setState(() => _ready = true);
  }

  void _onUpdate() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _seekDebounce?.cancel();
    final controller = _controller;
    _controller = null;
    if (controller != null) {
      controller.removeListener(_onUpdate);
      controller.dispose();
    }
    unawaited(coolDownNativeVideoResources());
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
    final position = controller.value.position;
    try {
      await controller.pause();
      controller.removeListener(_onUpdate);
      await controller.dispose();
      if (_controller == controller) _controller = null;
      await coolDownNativeVideoResources(
        delay: const Duration(milliseconds: 550),
      );
      final used = await widget.onFrameSelected(position);
      // extraction failed, so give the player back instead of a dead spinner
      if (!used && mounted) {
        await _init();
        _controller?.seekTo(position);
      }
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
    if (_failed) {
      return ColoredBox(
        color: AppColors.video,
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.xl),
            child: Text(
              "This video can't be played. Go back and pick another one.",
              textAlign: TextAlign.center,
              style: Theme.of(
                context,
              ).textTheme.bodyLarge?.copyWith(color: AppColors.onVideo),
            ),
          ),
        ),
      );
    }
    final controller = _controller;
    if (!_ready || controller == null) {
      return const ColoredBox(
        color: AppColors.video,
        child: Center(
          child: CircularProgressIndicator(color: AppColors.onVideo),
        ),
      );
    }

    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final pos = controller.value.position;
    final dur = controller.value.duration;
    final playing = controller.value.isPlaying;

    final maxMs = dur.inMilliseconds <= 0 ? 1.0 : dur.inMilliseconds.toDouble();
    final sliderValueMs =
        (_scrubbing
                ? (_scrubValueMs ?? pos.inMilliseconds.toDouble())
                : pos.inMilliseconds.toDouble())
            .clamp(0.0, maxMs)
            .toDouble();
    final shownPos = Duration(milliseconds: sliderValueMs.toInt());

    return Column(
      children: [
        Expanded(
          child: ColoredBox(
            color: AppColors.video,
            child: Center(
              child: AspectRatio(
                aspectRatio: controller.value.aspectRatio,
                child: VideoPlayer(controller),
              ),
            ),
          ),
        ),
        Container(
          decoration: BoxDecoration(
            color: scheme.surfaceContainerLow,
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(AppRadius.xl),
              topRight: Radius.circular(AppRadius.xl),
            ),
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
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Text(
                        _fmt(shownPos),
                        style: AppTheme.tabular(theme.textTheme.bodyMedium),
                      ),
                      Expanded(
                        child: Slider(
                          value: sliderValueMs,
                          max: maxMs,
                          onChangeStart: (_) {
                            if (controller.value.isPlaying) controller.pause();
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
                            controller.seekTo(
                              Duration(milliseconds: v.toInt()),
                            );
                            setState(() {
                              _scrubbing = false;
                              _scrubValueMs = null;
                            });
                          },
                        ),
                      ),
                      Text(
                        _fmt(dur),
                        style: AppTheme.tabular(
                          theme.textTheme.bodyMedium,
                        )?.copyWith(color: scheme.onSurfaceVariant),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      IconButton.filledTonal(
                        tooltip: 'Back 0.1 s',
                        icon: const Icon(Icons.keyboard_arrow_left),
                        onPressed: _stepBack,
                      ),
                      const SizedBox(width: AppSpacing.md),
                      IconButton.filled(
                        tooltip: playing ? 'Pause' : 'Play',
                        iconSize: 32,
                        style: IconButton.styleFrom(
                          minimumSize: const Size(56, 56),
                        ),
                        onPressed: _selecting
                            ? null
                            : () => playing
                                  ? controller.pause()
                                  : controller.play(),
                        icon: AnimatedSwitcher(
                          duration: const Duration(milliseconds: 250),
                          switchInCurve: Curves.easeInOut,
                          switchOutCurve: Curves.easeInOut,
                          child: Icon(
                            playing ? Icons.pause : Icons.play_arrow,
                            key: ValueKey(playing),
                          ),
                        ),
                      ),
                      const SizedBox(width: AppSpacing.md),
                      IconButton.filledTonal(
                        tooltip: 'Forward 0.1 s',
                        icon: const Icon(Icons.keyboard_arrow_right),
                        onPressed: _stepForward,
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: _selecting ? null : _select,
                      icon: _selecting
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.check),
                      label: const Text('Use this frame'),
                    ),
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
