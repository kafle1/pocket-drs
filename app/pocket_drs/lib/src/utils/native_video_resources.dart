// one native video job at a time: parallel decoders run android out of ImageReader buffers
Future<void> _chain = Future<void>.value();

Future<T> runWithNativeVideoResources<T>(Future<T> Function() operation) {
  final run = _chain.then((_) => operation());
  _chain = run.then((_) {}, onError: (_) {});
  return run;
}
