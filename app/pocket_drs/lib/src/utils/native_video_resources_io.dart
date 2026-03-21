import 'dart:async';

Future<void> _resourceChain = Future<void>.value();

Future<T> runWithNativeVideoResources<T>(Future<T> Function() operation) {
  final completer = Completer<T>();

  final scheduled = _resourceChain.catchError((_) {}).then((_) async {
    try {
      completer.complete(await operation());
    } catch (error, stackTrace) {
      completer.completeError(error, stackTrace);
    }
  });

  _resourceChain = scheduled.then((_) {}, onError: (_) {});
  return completer.future;
}

Future<void> coolDownNativeVideoResources({Duration delay = const Duration(milliseconds: 450)}) {
  return Future<void>.delayed(delay);
}