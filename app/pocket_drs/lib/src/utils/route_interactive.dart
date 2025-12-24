import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

/// Returns true when the current route is fully on-screen and safe to navigate.
///
/// In debug builds, calling Navigator.pop/push while a route transition is still
/// in progress can trigger Navigator's "_debugLocked" assertions.
bool routeIsInteractive(BuildContext context) {
  final navigator = Navigator.maybeOf(context);
  if (navigator?.userGestureInProgress ?? false) return false;

  final route = ModalRoute.of(context);
  if (route == null) return true;
  if (!route.isCurrent) return false;

  final animation = route.animation;
  if (animation == null) return true;

  return animation.status == AnimationStatus.completed;
}

/// Waits until the current route is fully on-screen and safe to navigate.
///
/// Use this before calling `Navigator.push/pop` from `initState` or callbacks
/// that can fire during transitions.
Future<void> waitForRouteInteractive(BuildContext context, {
  Duration pollInterval = const Duration(milliseconds: 16),
  Duration timeout = const Duration(seconds: 2),
}) async {
  final deadline = DateTime.now().add(timeout);

  // Ensure at least one frame has been produced.
  await SchedulerBinding.instance.endOfFrame;
  if (!context.mounted) return;

  while (!routeIsInteractive(context)) {
    if (!context.mounted) return;
    if (DateTime.now().isAfter(deadline)) return;
    await Future<void>.delayed(pollInterval);
    if (!context.mounted) return;
  }
}
