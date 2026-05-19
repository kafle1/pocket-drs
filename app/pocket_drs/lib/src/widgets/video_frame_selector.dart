import 'dart:async';
import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../utils/native_video_resources.dart';
import '../utils/video_controller_factory.dart';
import 'drs_button.dart';

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
    try {
      final controller = createVideoPlayerController(widget.videoPath);
      await runWithNativeVideoResources(() async {
        await coolDownNativeVideoResources(delay: const Duration(milliseconds: 350));
        await controller.initialize();
      });
      _controller = controller;
      controller.addListener(_onUpdate);
      if (mounted) setState(() => _ready = true);
    } catch (_) {
      final controller = _controller;
      try {
        await controller?.dispose();
      } catch (_) {}
      _controller = null;
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Failed to load video')),
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
    try {
      await controller.pause();
      controller.removeListener(_onUpdate);
      await controller.dispose();
      if (_controller == controller) _controller = null;
      await coolDownNativeVideoResources(delay: const Duration(milliseconds: 550));
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
    final scheme = theme.colorScheme;
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
        Expanded(
          child: Container(
            color: AppColors.inkBlack,
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
                      Text(
                        _fmt(shownPos),
                        style: AppTypography.mono(theme.textTheme.labelMedium),
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
                            controller.seekTo(Duration(milliseconds: v.toInt()));
                            setState(() {
                              _scrubbing = false;
                              _scrubValueMs = null;
                            });
                          },
                        ),
                      ),
                      Text(
                        _fmt(dur),
                        style: AppTypography.mono(theme.textTheme.labelMedium)?.copyWith(
                          color: scheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      _MiniButton(
                        icon: Icons.skip_previous,
                        label: '-0.1s',
                        onTap: _stepBack,
                      ),
                      const SizedBox(width: AppSpacing.md),
                      _MiniButton(
                        icon: playing ? Icons.pause : Icons.play_arrow,
                        large: true,
                        onTap: _selecting ? null : () => playing ? controller.pause() : controller.play(),
                      ),
                      const SizedBox(width: AppSpacing.md),
                      _MiniButton(
                        icon: Icons.skip_next,
                        label: '+0.1s',
                        onTap: _stepForward,
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  DrsButton(
                    label: 'USE THIS FRAME',
                    icon: Icons.check_circle_outline,
                    onPressed: _selecting ? null : _select,
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

class _MiniButton extends StatelessWidget {
  const _MiniButton({required this.icon, this.onTap, this.label, this.large = false});
  final IconData icon;
  final VoidCallback? onTap;
  final String? label;
  final bool large;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final size = large ? 48.0 : 40.0;
    final disabled = onTap == null;
    return Material(
      color: large && !disabled ? scheme.onSurface : Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.sm),
        side: BorderSide(color: scheme.outline, width: 1),
      ),
      child: InkWell(
        onTap: onTap,
        child: SizedBox(
          width: label != null ? null : size,
          height: size,
          child: Padding(
            padding: label != null ? const EdgeInsets.symmetric(horizontal: 12) : EdgeInsets.zero,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  icon,
                  size: large ? 22 : 18,
                  color: large && !disabled ? scheme.surface : scheme.onSurface,
                ),
                if (label != null) ...[
                  const SizedBox(width: AppSpacing.xs + 2),
                  Text(
                    label!.toUpperCase(),
                    style: TextStyle(
                      color: disabled ? scheme.onSurfaceVariant : scheme.onSurface,
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 1.2,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
