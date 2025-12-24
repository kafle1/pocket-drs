import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Lays out a tall portrait video with controls beneath it without overflowing.
///
/// Many cricket clips are recorded in portrait (e.g., 9:16). If we naively render
/// the video at full width using an [AspectRatio], the resulting height can
/// consume almost the whole screen, pushing controls off-screen and causing a
/// RenderFlex overflow.
///
/// This widget caps the video height and makes the controls area scrollable.
class ReviewLayout extends StatelessWidget {
  const ReviewLayout({
    super.key,
    required this.video,
    required this.controls,
  });

  final Widget video;
  final Widget controls;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        // Keep video reasonably sized so core controls stay discoverable.
        // On very small screens, the controls area can scroll.
        final videoHeight = math.min(
          360.0,
          math.max(160.0, constraints.maxHeight * 0.40),
        );

        return Column(
          children: [
            SizedBox(
              height: videoHeight,
              width: double.infinity,
              child: Center(child: video),
            ),
            Expanded(
              child: SingleChildScrollView(
                child: controls,
              ),
            ),
          ],
        );
      },
    );
  }
}
