import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:share_plus/share_plus.dart';

import '../analysis/frame_decoder.dart';
import '../api/analysis_result.dart';
import '../reviews/reviews.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'trajectory_video_view.dart';
import 'verdict.dart';

// 4:5 at 3x is 1080 by 1350, the shape a chat app shows whole without cropping
const _card = Size(360, 450);

/// Shows the verdict card for [review] with a button that hands it to the share sheet.
Future<void> showShareCard(BuildContext context, Review review) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => _ShareSheet(review: review),
  );
}

class _ShareSheet extends StatefulWidget {
  const _ShareSheet({required this.review});
  final Review review;

  @override
  State<_ShareSheet> createState() => _ShareSheetState();
}

class _ShareSheetState extends State<_ShareSheet> {
  final _key = GlobalKey();
  late final Future<Uint8List?> _frame = _loadFrame();
  bool _sharing = false;

  // the frame where the ball meets the batter, so the drawn path ends on something
  Future<Uint8List?> _loadFrame() {
    final r = widget.review.result!;
    final at =
        r.overlay?.impact?.tMs ??
        (r.track.points.isEmpty ? 0 : r.track.points.last.t);
    return decodeFrameJpeg(videoPath: widget.review.clip, timeMs: at);
  }

  Future<void> _share() async {
    setState(() => _sharing = true);
    try {
      final boundary =
          _key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
      final image = await boundary.toImage(pixelRatio: 3);
      final png = await image.toByteData(format: ui.ImageByteFormat.png);
      image.dispose();
      final file = File(
        '${Directory.systemTemp.path}/pocket_drs_review_'
        '${DateTime.now().millisecondsSinceEpoch}.png',
      );
      await file.writeAsBytes(png!.buffer.asUint8List());
      await SharePlus.instance.share(
        ShareParams(
          files: [XFile(file.path, mimeType: 'image/png')],
          text: 'LBW review from Pocket DRS',
        ),
      );
    } catch (e) {
      debugPrint('[SHARE] $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("Couldn't make the picture. Try again."),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _sharing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          0,
          AppSpacing.lg,
          AppSpacing.lg,
        ),
        child: FutureBuilder(
          future: _frame,
          builder: (context, snap) {
            final ready = snap.connectionState == ConnectionState.done;
            return Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('Share this call', style: theme.textTheme.titleLarge),
                const SizedBox(height: AppSpacing.md),
                ConstrainedBox(
                  constraints: BoxConstraints(
                    maxHeight: MediaQuery.sizeOf(context).height * 0.55,
                  ),
                  child: FittedBox(
                    child: ready
                        ? RepaintBoundary(
                            key: _key,
                            child: ShareCard(
                              result: widget.review.result!,
                              frame: snap.data,
                              at: widget.review.createdAt,
                            ),
                          )
                        : SizedBox.fromSize(
                            size: _card,
                            child: const Center(
                              child: CircularProgressIndicator(),
                            ),
                          ),
                  ),
                ),
                const SizedBox(height: AppSpacing.lg),
                FilledButton.icon(
                  onPressed: ready && !_sharing ? _share : null,
                  icon: const Icon(Icons.share_outlined),
                  label: const Text('Share picture'),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

/// The verdict as one picture: the frame with the ball's path, the call and the three checks.
class ShareCard extends StatelessWidget {
  const ShareCard({
    super.key,
    required this.result,
    required this.frame,
    required this.at,
  });
  final AnalysisResult result;
  // null when the clip gave no frame; the card still carries the call
  final Uint8List? frame;
  final DateTime at;

  @override
  Widget build(BuildContext context) {
    final lbw = result.lbw!;
    final aspect = result.imageHeight > 0
        ? result.imageWidth / result.imageHeight
        : 9 / 16;
    final wide = aspect > 1;
    final theme = AppTheme.dark();
    final overlay = result.overlay;
    final frameBox = ClipRRect(
      borderRadius: BorderRadius.circular(AppRadius.lg),
      child: ColoredBox(
        color: theme.colorScheme.surfaceContainer,
        child: Center(
          child: AspectRatio(
            aspectRatio: aspect,
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (frame case final bytes?)
                  Image.memory(bytes, fit: BoxFit.fill),
                if (overlay != null)
                  CustomPaint(
                    painter: TrajectoryPainter(
                      result: result,
                      overlay: overlay,
                      nowMs: 1 << 30,
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
    final c = lbw.confidence;
    final caption = [
      if (c != null) surenessWords(c),
      MaterialLocalizations.of(context).formatMediumDate(at),
    ].join('  ·  ');
    final info = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisAlignment: MainAxisAlignment.end,
      children: [
        Text(
          'POCKET DRS  ·  LBW REVIEW',
          style: AppTheme.caps(
            theme.textTheme.labelSmall,
          )?.copyWith(color: theme.colorScheme.primary),
        ),
        const SizedBox(height: AppSpacing.md),
        DecisionBanner(lbw: lbw),
        const SizedBox(height: AppSpacing.sm),
        CheckTiles(lbw: lbw, axis: wide ? Axis.horizontal : Axis.vertical),
        const SizedBox(height: AppSpacing.md),
        Text(
          caption,
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
      ],
    );
    // a fixed layout: the picture must look the same whatever the phone's text size
    return MediaQuery(
      data: MediaQuery.of(
        context,
      ).copyWith(textScaler: TextScaler.noScaling, disableAnimations: true),
      child: Theme(
        data: theme,
        child: SizedBox.fromSize(
          size: _card,
          child: ColoredBox(
            color: AppColors.video,
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: wide
                  ? Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(child: frameBox),
                        const SizedBox(height: AppSpacing.md),
                        info,
                      ],
                    )
                  : Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(flex: 9, child: frameBox),
                        const SizedBox(width: AppSpacing.md),
                        Expanded(flex: 11, child: info),
                      ],
                    ),
            ),
          ),
        ),
      ),
    );
  }
}
