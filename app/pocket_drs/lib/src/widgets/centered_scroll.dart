import 'package:flutter/material.dart';

/// Vertically centers [child] when it fits the viewport, and scrolls instead of
/// overflowing when it does not — small screens, large system fonts, or an open
/// keyboard. Use for full-screen empty / error / placeholder states whose
/// content is otherwise a centered [Column].
class CenteredScroll extends StatelessWidget {
  const CenteredScroll({super.key, required this.child, this.padding});

  final Widget child;
  final EdgeInsetsGeometry? padding;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        return SingleChildScrollView(
          padding: padding,
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: constraints.maxHeight),
            child: IntrinsicHeight(child: child),
          ),
        );
      },
    );
  }
}
