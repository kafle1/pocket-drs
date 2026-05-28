import 'dart:async';
import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../utils/native_video_resources.dart';
import '../utils/video_controller_factory.dart';
import 'drs_button.dart';

/// Pick the delivery sub-clip from a recorded or uploaded video.
///
/// Two handles on the timeline mark the segment start and end. The video
/// preview seeks to whichever handle is dragged so the user can frame the
/// trim against the actual footage. Only the bracketed segment is sent on
/// for analysis — the backend already supports a ``segment.{start_ms,
/// end_ms}`` field so we don't physically cut the file here; the optional
/// post-analysis cleanup in ``AnalyzeScreen`` (gated by the user setting)
/// deletes the source once the result lands.
class VideoTrimSelector extends StatefulWidget {
  const VideoTrimSelector({
    super.key,
    required this.videoPath,
    required this.onTrimSelected,
  });

  final String videoPath;
  final void Function(Duration start, Duration end) onTrimSelected;

  @override
  State<VideoTrimSelector> createState() => _VideoTrimSelectorState();
}

class _VideoTrimSelectorState extends State<VideoTrimSelector> {
  VideoPlayerController? _controller;
  bool _ready = false;
  bool _selecting = false;

  // Range slider state — units are video milliseconds.
  RangeValues? _range;
  Timer? _seekDebounce;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    try {
      final controller = createVideoPlayerController(widget.videoPath);
      await runWithNativeVideoResources(() async {
        await coolDownNativeVideoResources(
          delay: const Duration(milliseconds: 350),
        );
        await controller.initialize();
      });
      _controller = controller;
      controller.addListener(_onUpdate);
      final dur = controller.value.duration.inMilliseconds.toDouble();
      _range = RangeValues(0.0, dur);
      if (mounted) setState(() => _ready = true);
    } catch (_) {
      final controller = _controller;
      try {
        await controller?.dispose();
      } catch (_) {}
      _controller = null;
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('Failed to load video')));
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
    _seekDebounce = Timer(const Duration(milliseconds: 150), () {
      if (!mounted) return;
      _controller?.seekTo(Duration(milliseconds: ms));
    });
  }

  Future<void> _confirm() async {
    if (_selecting) return;
    final controller = _controller;
    final range = _range;
    if (controller == null || range == null) return;
    if (range.end - range.start < 200) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Pick a segment of at least 0.2s')),
      );
      return;
    }
    setState(() => _selecting = true);
    try {
      await controller.pause();
      widget.onTrimSelected(
        Duration(milliseconds: range.start.toInt()),
        Duration(milliseconds: range.end.toInt()),
      );
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
    final range = _range;
    if (controller == null || range == null) {
      return const Center(child: CircularProgressIndicator());
    }

    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final dur = controller.value.duration;
    final maxMs = dur.inMilliseconds <= 0 ? 1.0 : dur.inMilliseconds.toDouble();
    final segMs = (range.end - range.start).toInt();

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
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        _fmt(Duration(milliseconds: range.start.toInt())),
                        style: AppTypography.mono(theme.textTheme.labelMedium),
                      ),
                      Text(
                        'SEGMENT  ${(segMs / 1000).toStringAsFixed(1)}s',
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: AppColors.signalRed,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 1.4,
                        ),
                      ),
                      Text(
                        _fmt(Duration(milliseconds: range.end.toInt())),
                        style: AppTypography.mono(
                          theme.textTheme.labelMedium,
                        )?.copyWith(color: scheme.onSurfaceVariant),
                      ),
                    ],
                  ),
                  RangeSlider(
                    min: 0.0,
                    max: maxMs,
                    values: RangeValues(
                      range.start.clamp(0.0, maxMs),
                      range.end.clamp(0.0, maxMs),
                    ),
                    onChanged: (v) {
                      if (controller.value.isPlaying) controller.pause();
                      // Seek to whichever handle moved so the preview
                      // tracks the user's drag.
                      final movedStart = (v.start != range.start);
                      final target = movedStart ? v.start : v.end;
                      setState(() {
                        _range = v;
                      });
                      _scheduleSeekMs(target.toInt());
                    },
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    'Drag the handles to bracket the delivery. Only this segment is analysed.',
                    textAlign: TextAlign.center,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  DrsButton(
                    label: 'USE SEGMENT',
                    icon: Icons.check_circle_outline,
                    onPressed: _selecting ? null : _confirm,
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
