import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pocket_drs/src/utils/route_interactive.dart';

class _ProbeRoute extends StatelessWidget {
  const _ProbeRoute({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final interactive = routeIsInteractive(context);
    return Scaffold(
      body: Center(
        child: GestureDetector(
          onTap: interactive ? onTap : null,
          child: Text(interactive ? 'interactive' : 'transitioning'),
        ),
      ),
    );
  }
}

class _WaitForInteractiveRoute extends StatefulWidget {
  const _WaitForInteractiveRoute();

  @override
  State<_WaitForInteractiveRoute> createState() => _WaitForInteractiveRouteState();
}

class _WaitForInteractiveRouteState extends State<_WaitForInteractiveRoute> {
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    // Mimic production code that wants to navigate after the transition.
    waitForRouteInteractive(context).then((_) {
      if (!mounted) return;
      setState(() => _ready = true);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(child: Text(_ready ? 'ready' : 'waiting')),
    );
  }
}

void main() {
  testWidgets('routeIsInteractive becomes true after settle', (tester) async {
    late BuildContext rootContext;

    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) {
            rootContext = context;
            return Scaffold(
              body: Center(
                child: ElevatedButton(
                  onPressed: () {
                    Navigator.of(context).push(
                      PageRouteBuilder(
                        transitionDuration: const Duration(milliseconds: 300),
                        reverseTransitionDuration: const Duration(milliseconds: 300),
                        pageBuilder: (_, __, ___) => _ProbeRoute(onTap: () {}),
                      ),
                    );
                  },
                  child: const Text('push'),
                ),
              ),
            );
          },
        ),
      ),
    );

    await tester.tap(find.widgetWithText(ElevatedButton, 'push'));
    await tester.pumpAndSettle();
    expect(find.text('interactive', skipOffstage: false), findsOneWidget);

    // Sanity: root route is no longer current after pushing.
    expect(routeIsInteractive(rootContext), isFalse);
  });

  testWidgets('waitForRouteInteractive eventually completes after push', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: Builder(
              builder: (context) => ElevatedButton(
                onPressed: () {
                  Navigator.of(context).push(
                    PageRouteBuilder(
                      transitionDuration: const Duration(milliseconds: 300),
                      reverseTransitionDuration: const Duration(milliseconds: 300),
                      pageBuilder: (_, __, ___) => const _WaitForInteractiveRoute(),
                    ),
                  );
                },
                child: const Text('push'),
              ),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.widgetWithText(ElevatedButton, 'push'));
    await tester.pumpAndSettle();
    expect(find.text('ready', skipOffstage: false), findsOneWidget);
  });
}
