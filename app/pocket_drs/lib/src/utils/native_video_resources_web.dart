Future<T> runWithNativeVideoResources<T>(Future<T> Function() operation) {
  return operation();
}

Future<void> coolDownNativeVideoResources({Duration delay = const Duration(milliseconds: 0)}) {
  return Future<void>.delayed(delay);
}