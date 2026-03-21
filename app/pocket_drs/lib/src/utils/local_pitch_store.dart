import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import '../models/pitch.dart';

class LocalPitchStore {
  Future<File> _file() async {
    final dir = await getApplicationDocumentsDirectory();
    final storeDir = Directory('${dir.path}/pocket_drs/pitches');
    await storeDir.create(recursive: true);
    return File('${storeDir.path}/pitches_index.json');
  }

  Future<List<Pitch>> loadAll() async {
    final file = await _file();
    if (!await file.exists()) {
      return const <Pitch>[];
    }

    final raw = await file.readAsString();
    if (raw.trim().isEmpty) {
      return const <Pitch>[];
    }

    final decoded = jsonDecode(raw);
    if (decoded is! List) {
      return const <Pitch>[];
    }

    final pitches = decoded
        .whereType<Map>()
        .map((item) => Pitch.fromJson(item.cast<String, Object?>()))
        .toList(growable: false);

    pitches.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    return pitches;
  }

  Future<Pitch?> loadById(String id) async {
    final all = await loadAll();
    for (final pitch in all) {
      if (pitch.id == id) {
        return pitch;
      }
    }
    return null;
  }

  Future<void> save(Pitch pitch) async {
    final all = await loadAll();
    final updated = <Pitch>[pitch, ...all.where((p) => p.id != pitch.id)];
    await _writeAll(updated);
  }

  Future<void> delete(String id) async {
    final all = await loadAll();
    await _writeAll(all.where((p) => p.id != id).toList(growable: false));
  }

  Future<void> replaceAll(List<Pitch> pitches) async {
    await _writeAll(pitches);
  }

  Future<void> _writeAll(List<Pitch> pitches) async {
    final file = await _file();
    final payload = pitches
        .map((pitch) => pitch.toJson())
        .toList(growable: false);
    await file.writeAsString(const JsonEncoder.withIndent('  ').convert(payload));
  }
}
