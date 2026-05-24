/// Open ``url`` in a new browser tab on web; no-op on native platforms.
///
/// The platform-specific implementation is picked at compile time via
/// conditional imports so this file stays a single, type-safe API while
/// the actual ``dart:html`` call only ships into the web bundle.
export 'web_open_stub.dart' if (dart.library.html) 'web_open_web.dart';
