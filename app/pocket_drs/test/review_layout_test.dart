import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pocket_drs/src/widgets/review_layout.dart';

void main() {
  testWidgets('ReviewLayout does not overflow on tall portrait videos', (tester) async {
    // Simulate a small-ish phone height where a portrait video would otherwise
    // push the controls off-screen.
    await tester.binding.setSurfaceSize(const Size(390, 600));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: ReviewLayout(
            video: ColoredBox(color: Colors.black),
            controls: Padding(
              padding: EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SizedBox(height: 12),
                  Text('Controls header'),
                  SizedBox(height: 12),
                  // Make controls intentionally tall.
                  SizedBox(height: 800, child: ColoredBox(color: Colors.blueGrey)),
                ],
              ),
            ),
          ),
        ),
      ),
    );

    // A RenderFlex overflow is reported as a FlutterError during layout.
    expect(tester.takeException(), isNull);
  });
}
