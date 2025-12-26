import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pocket_drs/src/screens/logs_screen.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('LogsScreen does not render log contents', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: LogsScreen(
          autoLoad: false,
          initialText: 'this-should-not-appear',
          initialPath: '/tmp/analysis_log.txt',
        ),
      ),
    );

    // We still allow export/copy, but we should not show the raw text in the UI.
    expect(find.textContaining('this-should-not-appear'), findsNothing);
    expect(find.byType(SelectableText), findsNothing);

    // UI should still indicate logs are captured.
    expect(find.textContaining('Logs captured:'), findsOneWidget);
  });
}
