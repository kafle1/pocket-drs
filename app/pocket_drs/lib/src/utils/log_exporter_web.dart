import 'dart:html' as html;

/// Downloads [contents] as a file in the browser.
Future<void> exportTextFile({
  required String filename,
  required String contents,
}) async {
  final bytes = contents.codeUnits;
  final blob = html.Blob([bytes], 'text/plain;charset=utf-8');
  final url = html.Url.createObjectUrlFromBlob(blob);

  final a = html.AnchorElement(href: url)
    ..download = filename
    ..style.display = 'none';

  html.document.body?.children.add(a);
  a.click();
  a.remove();

  html.Url.revokeObjectUrl(url);
}
