import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:pocket_drs/src/pocket_drs_app.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('PocketDrsApp builds', (tester) async {
    // ThemeController/AppSettings use SharedPreferences. Provide an in-memory
    // store so tests are deterministic and do not require platform channels.
    SharedPreferences.setMockInitialValues(<String, Object>{});

    await tester.pumpWidget(const PocketDrsApp());
    await tester.pumpAndSettle();

    // Basic smoke assertions: the home shell and bottom navigation are present.
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.text('Pitches'), findsWidgets);
    expect(find.text('Settings'), findsWidgets);
  });
}
