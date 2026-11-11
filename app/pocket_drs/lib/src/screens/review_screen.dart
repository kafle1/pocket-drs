import 'dart:io';
import 'dart:math' show min;

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/pocket_drs_api.dart';
import '../reviews/reviews.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../utils/app_settings.dart';
import '../widgets/ball_path_3d.dart';
import '../widgets/share_card.dart';
import '../widgets/stump_marker.dart';
import '../widgets/trajectory_video_view.dart';
import '../widgets/verdict.dart';

/// One review in whatever state it is in: being checked, called, refused or failed.
class ReviewScreen extends StatelessWidget {
  const ReviewScreen({super.key, required this.review, this.onAnother});
  final Review review;

  /// Starts the next ball, when this screen ends the analyse flow.
  final VoidCallback? onAnother;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: Reviews.instance,
      builder: (context, _) {
        final r = review;
        final (title, body) = switch (r.state) {
          ReviewState.sending ||
          ReviewState.checking => ('Checking the ball', _Progress(review: r)),
          ReviewState.done => (
            r.result!.hasCall ? 'The call' : 'No call',
            _Result(review: r, onAnother: onAnother),
          ),
          ReviewState.failed ||
          ReviewState.expired => ('Not checked', _Failed(review: r)),
        };
        return Scaffold(
          appBar: AppBar(title: Text(title)),
          body: AnimatedSwitcher(
            duration: const Duration(milliseconds: 220),
            child: KeyedSubtree(key: ValueKey(r.state), child: body),
          ),
        );
      },
    );
  }
}

/// Opens the saved frame so the stumps can be marked again, then sends the ball again.
Future<void> remarkStumps(BuildContext context, Review r) async {
  final messenger = ScaffoldMessenger.of(context);
  try {
    final frame = await File(r.frame).readAsBytes();
    if (!context.mounted) return;
    final marks = await Navigator.of(context).push<List<Offset?>>(
      MaterialPageRoute(
        builder: (_) => MarkStumpsScreen(
          frame: frame,
          marks: r.stumps,
          suspect: r.result?.worstMark,
        ),
      ),
    );
    if (marks == null) return;
    Reviews.instance.remark(r, marks, await AppSettings.getPitchSetup());
  } on FileSystemException {
    messenger.showSnackBar(
      const SnackBar(
        content: Text(
          "This ball's frame is missing, so it can't be marked again.",
        ),
      ),
    );
  }
}

const _steps = [
  'Sending your clip',
  'Waiting in line',
  'Finding the ball',
  'Making the call',
];

int _step(Review r) => r.state == ReviewState.sending
    ? 0
    : switch (r.stage) {
        'queued' || null => 1,
        'starting' || 'decode' || 'calibration' || 'tracking' => 2,
        _ => 3,
      };

// what sits at the right of the current step: the place in line, or how far the check has got
String? _aside(Review r, int i, int step) => switch (r.queue) {
  _ when i != step => null,
  1 when i == 1 => "You're next",
  final q? when i == 1 => '${q - 1} ahead of you',
  _ when i == 0 && r.sent != null => '${(r.sent! * 100).round()}%',
  _ when i > 1 && r.pct != null => '${r.pct}%',
  _ => null,
};

class _Progress extends StatelessWidget {
  const _Progress({required this.review});
  final Review review;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final step = _step(review);
    final sent = review.sent;
    // the upload has its own share until the server takes over
    final pct = sent != null && step == 0 ? (sent * 100).round() : review.pct;
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TweenAnimationBuilder<double>(
                tween: Tween(end: pct == null ? 0 : pct.clamp(0, 100) / 100),
                duration: const Duration(milliseconds: 300),
                curve: Curves.easeOutCubic,
                builder: (context, v, _) => LinearProgressIndicator(
                  value: pct == null ? null : v,
                  minHeight: 6,
                  borderRadius: BorderRadius.circular(3),
                ),
              ),
              const SizedBox(height: AppSpacing.xl),
              for (final (i, label) in _steps.indexed)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    children: [
                      SizedBox.square(
                        dimension: 24,
                        child: i < step
                            ? Icon(Icons.check_circle, color: scheme.primary)
                            : i == step
                            ? Padding(
                                padding: const EdgeInsets.all(3),
                                child: CircularProgressIndicator(
                                  strokeWidth: 2.5,
                                  color: scheme.primary,
                                ),
                              )
                            : Icon(
                                Icons.radio_button_unchecked,
                                color: scheme.outlineVariant,
                              ),
                      ),
                      const SizedBox(width: AppSpacing.md),
                      Expanded(
                        child: Text(
                          i == 0 && review.waitingTurn
                              ? 'Waiting for your last ball'
                              : label,
                          style: theme.textTheme.titleMedium?.copyWith(
                            color: i > step ? scheme.onSurfaceVariant : null,
                          ),
                        ),
                      ),
                      if (_aside(review, i, step) case final aside?)
                        Text(
                          aside,
                          style: AppTheme.tabular(
                            theme.textTheme.titleMedium,
                          )?.copyWith(color: scheme.primary),
                        ),
                    ],
                  ),
                ),
              if (review.waitingFor case final first?) ...[
                const SizedBox(height: AppSpacing.md),
                Text(
                  'The server checks one ball per account at a time, so this '
                  'one goes as soon as your last one is done.',
                  style: theme.textTheme.bodyMedium,
                ),
                const SizedBox(height: AppSpacing.sm),
                OutlinedButton(
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => ReviewScreen(review: first),
                    ),
                  ),
                  child: const Text('Open that ball'),
                ),
              ],
              const SizedBox(height: AppSpacing.xl),
              Text(
                'You can leave this screen. The check carries on, and the call '
                'shows up in your reviews on the home screen, even if you close the app.',
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: scheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
              OutlinedButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('Leave it running'),
              ),
              if (review.state == ReviewState.sending)
                TextButton(
                  onPressed: () => Reviews.instance.cancel(review),
                  child: const Text('Stop sending'),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Failed extends StatelessWidget {
  const _Failed({required this.review});
  final Review review;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final r = review;
    final expired = r.state == ReviewState.expired;
    final outdated = r.errorCode == 'app_outdated';
    return SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(AppSpacing.xl),
        children: [
          Icon(
            expired ? Icons.history_toggle_off : Icons.error_outline,
            size: 40,
            color: scheme.error,
          ),
          const SizedBox(height: AppSpacing.lg),
          Text(
            expired
                ? 'The server let this ball go'
                : "This ball wasn't checked",
            style: theme.textTheme.headlineSmall,
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            r.error ?? 'Something went wrong.',
            style: theme.textTheme.bodyLarge,
          ),
          const SizedBox(height: AppSpacing.xl),
          if (outdated && Platform.isAndroid)
            FilledButton.icon(
              onPressed: () => launchUrl(
                Uri.parse(kStoreUrl),
                mode: LaunchMode.externalApplication,
              ).ignore(),
              icon: const Icon(Icons.system_update_outlined),
              label: const Text('Update Pocket DRS'),
            ),
          if (r.retryable) ...[
            FilledButton.icon(
              onPressed: () => Reviews.instance.retry(r),
              icon: const Icon(Icons.refresh),
              label: Text(expired ? 'Send it again' : 'Try again'),
            ),
          ],
          const SizedBox(height: AppSpacing.md),
          TextButton(
            onPressed: () {
              Reviews.instance.delete(r);
              Navigator.pop(context);
            },
            child: const Text('Delete this ball'),
          ),
        ],
      ),
    );
  }
}

class _Result extends StatelessWidget {
  const _Result({required this.review, required this.onAnother});
  final Review review;
  final VoidCallback? onAnother;

  // drawn from the result kept on the phone, so it works offline and never expires
  void _open3D(BuildContext context) => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => Scaffold(
        backgroundColor: AppColors.video,
        appBar: AppBar(title: const Text('Ball path in 3D')),
        body: BallPath3D(
          result: review.result!,
          pitchLengthM: review.pitchLengthM,
          stumps: review.stumpSize,
        ),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final result = review.result!;
    final size = MediaQuery.sizeOf(context);
    final wide = size.width > size.height;
    final call = result.hasCall;
    final video = Expanded(
      child: ColoredBox(
        color: AppColors.video,
        child: TrajectoryVideoView(videoPath: review.clip, result: result),
      ),
    );
    final actions = <Widget>[
      if (call)
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: () => _open3D(context),
                icon: const Icon(Icons.view_in_ar_outlined),
                label: const Text('View in 3D'),
              ),
            ),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: () => showShareCard(context, review),
                icon: const Icon(Icons.share_outlined),
                label: const Text('Share'),
              ),
            ),
          ],
        )
      else
        OutlinedButton.icon(
          onPressed: () => remarkStumps(context, review),
          icon: const Icon(Icons.center_focus_strong_outlined),
          label: const Text('Mark the stumps again'),
        ),
      if (onAnother case final another?)
        FilledButton.icon(
          onPressed: another,
          icon: const Icon(Icons.sports_cricket),
          label: const Text('Check another ball'),
        ),
    ];
    final panel = DecoratedBox(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerLow,
      ),
      child: SafeArea(
        top: false,
        left: !wide,
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              call
                  ? VerdictSummary(result: result)
                  : NoCallSummary(result: result),
              for (final a in actions) ...[
                const SizedBox(height: AppSpacing.sm),
                a,
              ],
            ],
          ),
        ),
      ),
    );
    // on a tripod the phone is often sideways, where a panel under the video would leave it no room
    return wide
        ? Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              video,
              SizedBox(width: min(380, size.width * 0.5), child: panel),
            ],
          )
        : Column(
            children: [
              video,
              ConstrainedBox(
                constraints: BoxConstraints(maxHeight: size.height * 0.58),
                child: panel,
              ),
            ],
          );
  }
}
