import 'dart:convert';
import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

import '../analysis/calibration_config.dart';
import '../models/pitch.dart';

class PitchStore {
  PitchStore({SharedPreferences? prefs}) : _prefs = prefs;

  static const _pitchesKey = 'pitches_v1';

  final SharedPreferences? _prefs;

  Future<SharedPreferences> _getPrefs() async {
    return _prefs ?? SharedPreferences.getInstance();
  }

  Future<List<Pitch>> loadAll() async {
    final prefs = await _getPrefs();
    final raw = prefs.getString(_pitchesKey);
    if (raw == null || raw.isEmpty) return <Pitch>[];

    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) return <Pitch>[];
      final pitches = <Pitch>[];
      for (final v in decoded) {
        if (v is! Map) continue;
        try {
          final map = Map<String, Object?>.from(v);
          pitches.add(Pitch.fromJson(map));
        } catch (_) {
          // Skip corrupted entries.
        }
      }
      pitches.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
      return pitches;
    } catch (_) {
      return <Pitch>[];
    }
  }

  Future<void> saveAll(List<Pitch> pitches) async {
    final prefs = await _getPrefs();
    final list = pitches.map((p) => p.toJson()).toList(growable: false);
    await prefs.setString(_pitchesKey, jsonEncode(list));
  }

  Future<Pitch?> loadById(String id) async {
    final all = await loadAll();
    for (final p in all) {
      if (p.id == id) return p;
    }
    return null;
  }

  Future<Pitch> create({required String name}) async {
    final now = DateTime.now();
    final pitch = Pitch(
      id: _newId(),
      name: name.trim(),
      createdAt: now,
      updatedAt: now,
      calibration: null,
    );

    final all = await loadAll();
    all.insert(0, pitch);
    await saveAll(all);
    return pitch;
  }

  Future<Pitch> update(Pitch pitch) async {
    final all = await loadAll();
    final idx = all.indexWhere((p) => p.id == pitch.id);
    if (idx == -1) {
      all.insert(0, pitch);
    } else {
      all[idx] = pitch;
    }
    all.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    await saveAll(all);
    return pitch;
  }

  Future<void> delete(String id) async {
    final all = await loadAll();
    all.removeWhere((p) => p.id == id);
    await saveAll(all);
  }

  static CalibrationConfig defaultCalibration() => CalibrationConfig.defaults();

  String _newId() {
    final now = DateTime.now().microsecondsSinceEpoch;
    final rand = Random().nextInt(1 << 32);
    return '$now-$rand';
  }
}
