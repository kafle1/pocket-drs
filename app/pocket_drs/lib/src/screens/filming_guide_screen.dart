import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../utils/app_settings.dart';

/// Opens [screen], showing how to film first if this phone has never seen it.
Future<void> openWithGuide(BuildContext context, Widget screen) async {
  final nav = Navigator.of(context);
  final seen = await AppSettings.getGuideSeen();
  nav.push(
    MaterialPageRoute<void>(
      builder: (_) => seen ? screen : FilmingGuideScreen(then: screen),
    ),
  );
}

const _rules = [
  (
    Icons.videocam_outlined,
    "Stand behind the bowler's stumps",
    'A couple of metres back, at chest height, in line with the stumps. Zoom off, main lens.',
  ),
  (
    Icons.crop_free,
    'Both sets of stumps in view',
    'The far stumps and the near stumps fit in the frame, tops and feet.',
  ),
  (
    Icons.slow_motion_video,
    '60 frames a second',
    'Set the camera to 60 fps. At 30 the ball jumps too far between frames to follow.',
  ),
  (
    Icons.back_hand_outlined,
    'Keep the phone still',
    'A tripod, a bag or a fence post. If the phone moves, the stumps move with it.',
  ),
  (
    Icons.wb_sunny_outlined,
    'A red or pink ball in good light',
    'Film the whole delivery, from the hand to just after it reaches the batter.',
  ),
];

/// How to film a clip the app can call, shown before the first one and from the home screen.
class FilmingGuideScreen extends StatelessWidget {
  const FilmingGuideScreen({super.key, this.then});

  /// Where "Got it" goes; without it the guide simply closes.
  final Widget? then;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final next = then;
    return Scaffold(
      appBar: AppBar(title: const Text('How to film')),
      body: SafeArea(
        top: false,
        child: Column(
          children: [
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg,
                  0,
                  AppSpacing.lg,
                  AppSpacing.lg,
                ),
                children: [
                  ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child: const ColoredBox(
                      color: AppColors.video,
                      child: AspectRatio(
                        aspectRatio: 16 / 9,
                        child: CustomPaint(painter: _SetupDrawing()),
                      ),
                    ),
                  ),
                  const SizedBox(height: AppSpacing.xl),
                  for (final (icon, title, body) in _rules)
                    Padding(
                      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Container(
                            width: 40,
                            height: 40,
                            decoration: BoxDecoration(
                              color: scheme.primaryContainer,
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Icon(
                              icon,
                              color: scheme.onPrimaryContainer,
                              size: 22,
                            ),
                          ),
                          const SizedBox(width: AppSpacing.md),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(title, style: theme.textTheme.titleMedium),
                                const SizedBox(height: 2),
                                Text(
                                  body,
                                  style: theme.textTheme.bodyMedium?.copyWith(
                                    color: scheme.onSurfaceVariant,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: () async {
                    final nav = Navigator.of(context);
                    await AppSettings.setGuideSeen();
                    if (next == null) {
                      nav.pop();
                    } else {
                      nav.pushReplacement(
                        MaterialPageRoute<void>(builder: (_) => next),
                      );
                    }
                  },
                  child: const Text('Got it'),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The pitch from the side: phone on a tripod behind the near stumps, looking down the pitch.
class _SetupDrawing extends CustomPainter {
  const _SetupDrawing();

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;
    final ground = h * 0.78;
    final grass = Paint()..color = AppColors.notOut.withValues(alpha: 0.35);
    canvas.drawRect(Rect.fromLTRB(0, ground, w, h), grass);
    final pitch = Paint()
      ..color = const Color(0xFFB9A877).withValues(alpha: 0.6);
    final near = w * 0.24, far = w * 0.9;
    canvas.drawRect(Rect.fromLTRB(near, ground - 2, far, ground + 4), pitch);

    final stumps = Paint()
      ..color = AppColors.onVideo
      ..strokeWidth = 2.5
      ..strokeCap = StrokeCap.round;
    for (final x in [near, far]) {
      canvas.drawLine(Offset(x, ground), Offset(x, ground - h * 0.2), stumps);
    }

    // tripod and phone a little behind the near stumps
    final phoneX = w * 0.1;
    final eye = Offset(phoneX, ground - h * 0.42);
    final legs = Paint()
      ..color = AppColors.onVideo.withValues(alpha: 0.7)
      ..strokeWidth = 2;
    canvas.drawLine(eye, Offset(phoneX - 14, ground), legs);
    canvas.drawLine(eye, Offset(phoneX + 14, ground), legs);
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromCenter(center: eye, width: 10, height: 22),
        const Radius.circular(2),
      ),
      Paint()..color = AppColors.predicted,
    );

    // what the camera sees: both sets of stumps inside the view
    final view = Path()
      ..moveTo(eye.dx + 5, eye.dy)
      ..lineTo(far + 16, ground - h * 0.34)
      ..lineTo(far + 16, ground + 6)
      ..close();
    canvas.drawPath(
      view,
      Paint()..color = AppColors.predicted.withValues(alpha: 0.14),
    );
    canvas.drawPath(
      view,
      Paint()
        ..color = AppColors.predicted.withValues(alpha: 0.6)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.2,
    );

    // the ball's path from the bowler's hand to the batter
    final ball = Path()
      ..moveTo(near + w * 0.04, ground - h * 0.3)
      ..quadraticBezierTo(w * 0.55, ground - h * 0.12, w * 0.7, ground)
      ..quadraticBezierTo(
        w * 0.8,
        ground - h * 0.12,
        far - 6,
        ground - h * 0.12,
      );
    canvas.drawPath(
      ball,
      Paint()
        ..color = AppColors.track
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.5,
    );
  }

  @override
  bool shouldRepaint(_SetupDrawing old) => false;
}
