import 'package:flutter/material.dart';

import '../api/analysis_result.dart';
import '../api/pocket_drs_api.dart' show notCounted;
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';

/// How sure the call is, in the words a player would use. Below [surePoint] the call reads as a guess.
const surePoint = 0.65;

String surenessWords(double c) => switch (c) {
  >= 0.85 => 'Very sure',
  >= surePoint => 'Fairly sure',
  >= 0.45 => 'Not very sure',
  _ => 'Unsure',
};

String _cap(String s) => s.isEmpty ? s : s[0].toUpperCase() + s.substring(1);

/// One check's value and colour, from the call and the server's tone for that row.
({String value, Color? fill}) checkValue(LbwResult lbw, String row) {
  final raw = lbw.tones[row];
  final tone = raw is String ? raw : null;
  final close = tone == 'umpires_call';
  final value = switch (row) {
    _ when close => "Umpire's call",
    'pitching' => lbw.pitchedInLine ? 'In line' : 'Outside leg',
    'impact' => lbw.impactInLine ? 'In line' : 'Outside line',
    _ => switch (lbw.wicketsHitting) {
      true => 'Hitting',
      false => 'Missing',
      null => 'No path',
    },
  };
  return (
    value: value,
    fill: row == 'wickets' && lbw.wicketsHitting == null
        ? null
        : AppColors.tone(tone),
  );
}

const checkRows = [
  ('pitching', 'Pitching'),
  ('impact', 'Impact'),
  ('wickets', 'Wickets'),
];

/// The three checks as tiles, red against the batter, green for him, amber too close to call.
class CheckTiles extends StatelessWidget {
  const CheckTiles({super.key, required this.lbw, this.axis = Axis.horizontal});
  final LbwResult lbw;
  final Axis axis;

  @override
  Widget build(BuildContext context) {
    final tiles = [
      for (final (i, (row, label)) in checkRows.indexed)
        _Reveal(
          delay: 120 + 80 * i,
          child: _CheckTile(label: label, check: checkValue(lbw, row)),
        ),
    ];
    final gap = axis == Axis.horizontal
        ? const SizedBox(width: AppSpacing.sm)
        : const SizedBox(height: AppSpacing.sm);
    final flex = Flex(
      direction: axis,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final (i, t) in tiles.indexed) ...[
          if (i > 0) gap,
          axis == Axis.horizontal ? Expanded(child: t) : t,
        ],
      ],
    );
    // side by side, a two-line value makes every tile as tall as it
    return axis == Axis.horizontal ? IntrinsicHeight(child: flex) : flex;
  }
}

class _CheckTile extends StatelessWidget {
  const _CheckTile({required this.label, required this.check});
  final String label;
  final ({String value, Color? fill}) check;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final fill = check.fill;
    final ink = fill == null
        ? scheme.onSurfaceVariant
        : AppColors.onVerdict(fill);
    return Semantics(
      label: '$label: ${check.value}',
      excludeSemantics: true,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(AppRadius.sm),
        child: ColoredBox(
          color: fill ?? scheme.surfaceContainerHigh,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                color: scheme.surfaceContainerHighest,
                padding: const EdgeInsets.fromLTRB(10, 6, 10, 5),
                child: Text(
                  label.toUpperCase(),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.caps(
                    theme.textTheme.labelSmall,
                  )?.copyWith(color: scheme.onSurfaceVariant),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(10, 8, 10, 9),
                child: Text(
                  check.value,
                  maxLines: 2,
                  style: theme.textTheme.titleSmall?.copyWith(
                    color: ink,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// A sure call fills its colour; an unsure one is only outlined, so the two can never be mistaken.
class DecisionBanner extends StatelessWidget {
  const DecisionBanner({super.key, required this.lbw});
  final LbwResult lbw;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final colour = AppColors.verdict(lbw.decision);
    final sure = (lbw.confidence ?? 1) >= surePoint;
    final filled = colour != null && sure;
    final ink = colour == null
        ? scheme.onSurfaceVariant
        : filled
        ? AppColors.onVerdict(colour)
        : colour;
    return _Reveal(
      scale: true,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(
          vertical: AppSpacing.lg,
          horizontal: AppSpacing.lg,
        ),
        decoration: BoxDecoration(
          color: filled ? colour : scheme.surfaceContainerHigh,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: filled || colour == null
              ? null
              : Border.all(color: colour, width: 2.5),
        ),
        child: Column(
          children: [
            FittedBox(
              fit: BoxFit.scaleDown,
              child: Text(
                lbw.decision.label.toUpperCase(),
                maxLines: 1,
                style: theme.textTheme.displaySmall?.copyWith(
                  color: ink,
                  letterSpacing: 0.5,
                ),
              ),
            ),
            if (!sure) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(
                'Low sureness: treat this call as a guess',
                textAlign: TextAlign.center,
                style: theme.textTheme.labelLarge?.copyWith(color: ink),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// How sure the app is, as words and a five-step meter, with the margin at the stumps.
class SurenessRow extends StatelessWidget {
  const SurenessRow({super.key, required this.lbw});
  final LbwResult lbw;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final c = lbw.confidence;
    final y = lbw.u95YM, z = lbw.u95ZM;
    final margin = y == null || z == null
        ? null
        : 'At the stumps the ball could be off by up to '
              '${(y * 100).round()} cm sideways and ${(z * 100).round()} cm in height.';
    if (c == null && margin == null) return const SizedBox.shrink();
    final steps = c == null ? 0 : (c * 5).ceil().clamp(1, 5);
    final colour = c == null || c >= surePoint
        ? scheme.primary
        : AppColors.umpiresCall;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (c != null)
          Semantics(
            label: 'How sure: ${surenessWords(c)}',
            excludeSemantics: true,
            child: Row(
              children: [
                Text(
                  'HOW SURE',
                  style: AppTheme.caps(
                    theme.textTheme.labelSmall,
                  )?.copyWith(color: scheme.onSurfaceVariant),
                ),
                const SizedBox(width: AppSpacing.md),
                for (var i = 0; i < 5; i++)
                  Container(
                    width: 18,
                    height: 8,
                    margin: const EdgeInsets.only(right: 3),
                    decoration: BoxDecoration(
                      color: i < steps
                          ? colour
                          : scheme.surfaceContainerHighest,
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                const SizedBox(width: AppSpacing.sm),
                Flexible(
                  child: Text(
                    surenessWords(c),
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.titleSmall,
                  ),
                ),
              ],
            ),
          ),
        if (margin != null) ...[
          if (c != null) const SizedBox(height: AppSpacing.sm),
          Text(
            margin,
            style: theme.textTheme.bodySmall?.copyWith(
              color: scheme.onSurfaceVariant,
            ),
          ),
        ],
      ],
    );
  }
}

/// The call: decision, the three checks, how sure, and the server's reason.
class VerdictSummary extends StatelessWidget {
  const VerdictSummary({super.key, required this.result});
  final AnalysisResult result;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final lbw = result.lbw!;
    final notes = [
      if (lbw.decision != LbwDecisionKey.out) _cap(lbw.reason),
      ...result.warnings,
    ].where((l) => l.isNotEmpty);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        DecisionBanner(lbw: lbw),
        const SizedBox(height: AppSpacing.md),
        CheckTiles(lbw: lbw),
        const SizedBox(height: AppSpacing.lg),
        SurenessRow(lbw: lbw),
        for (final n in notes) ...[
          const SizedBox(height: AppSpacing.sm),
          Text(n, style: theme.textTheme.bodyMedium),
        ],
      ],
    );
  }
}

// one concrete thing to change for each of the server's no-call reasons
const _tips = {
  'phone_too_far':
      "Stand right behind the bowler's stumps with the zoom off, so the far stumps look bigger.",
  'no_ball':
      'Use a red or pink ball in good light, with the whole pitch from stumps to stumps in view.',
  'still_in_flight':
      'Trim the clip so it ends just after the ball reaches the batter.',
  'path_mismatch':
      'Zoom right in on each stump corner when you mark it, then send the ball again.',
  'no_stump_path':
      'Keep the ball in view all the way to the batter, with the phone held still.',
  'too_unsure':
      'Film at 60 frames a second with the phone on a tripod, and mark the corners zoomed in.',
  'lost_before_batter':
      'Film against a plain background so the ball stays visible up to the pad.',
};
const _generalTip =
    "Film from right behind the bowler's stumps with both sets of stumps in view, "
    'at 60 frames a second, with the phone held still.';

/// The server refused to call this ball: its reason is the headline, with one tip for the next clip.
class NoCallSummary extends StatelessWidget {
  const NoCallSummary({super.key, required this.result});
  final AnalysisResult result;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final reason = result.warnings.isEmpty
        ? "The ball's path couldn't be worked out well enough to make a call."
        : result.warnings.first;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'NO CALL',
          style: AppTheme.caps(
            theme.textTheme.labelMedium,
          )?.copyWith(color: scheme.onSurfaceVariant),
        ),
        const SizedBox(height: AppSpacing.xs),
        Text(reason, style: theme.textTheme.titleLarge),
        const SizedBox(height: AppSpacing.xs),
        Text(
          notCounted,
          style: theme.textTheme.bodySmall?.copyWith(
            color: scheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        DecoratedBox(
          decoration: BoxDecoration(
            color: scheme.primaryContainer,
            borderRadius: BorderRadius.circular(AppRadius.lg),
          ),
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  Icons.tips_and_updates_outlined,
                  color: scheme.onPrimaryContainer,
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Next time',
                        style: theme.textTheme.titleSmall?.copyWith(
                          color: scheme.onPrimaryContainer,
                        ),
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Text(
                        _tips[result.noCallCode] ?? _generalTip,
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: scheme.onPrimaryContainer,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        for (final n in result.warnings.skip(1)) ...[
          const SizedBox(height: AppSpacing.sm),
          Text(n, style: theme.textTheme.bodyMedium),
        ],
      ],
    );
  }
}

/// The one reveal in the app: the call settles in, then each check follows it.
class _Reveal extends StatelessWidget {
  const _Reveal({required this.child, this.delay = 0, this.scale = false});
  final Widget child;
  final int delay;
  final bool scale;

  @override
  Widget build(BuildContext context) {
    if (MediaQuery.disableAnimationsOf(context)) return child;
    const run = 420;
    final total = delay + run;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: Duration(milliseconds: total),
      builder: (context, t, child) {
        final k = Curves.easeOutQuart.transform(
          ((t * total - delay) / run).clamp(0.0, 1.0),
        );
        return Opacity(
          opacity: k,
          child: Transform.scale(
            scale: scale ? 0.9 + 0.1 * k : 1,
            child: Transform.translate(
              offset: Offset(0, scale ? 0 : 8 * (1 - k)),
              child: child,
            ),
          ),
        );
      },
      child: child,
    );
  }
}
