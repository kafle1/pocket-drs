import 'dart:math';

import '../analysis/calibration_config.dart';
import '../models/pitch.dart';
import '../services/auth_service.dart';
import '../services/firestore_service.dart';

class PitchStore {
  PitchStore._(this._auth, this._firestore);

  factory PitchStore({AuthService? authService, FirestoreService? firestoreService}) {
    final auth = authService ?? AuthService();
    final firestore = firestoreService ?? FirestoreService(auth);
    return PitchStore._(auth, firestore);
  }

  final AuthService _auth;
  final FirestoreService _firestore;

  Future<List<Pitch>> loadAll() async {
    if (!_auth.isAuthenticated) {
      throw StateError('User not authenticated');
    }
    return _firestore.getPitches();
  }

  Future<Pitch?> loadById(String id) async {
    if (!_auth.isAuthenticated) {
      throw StateError('User not authenticated');
    }
    return _firestore.getPitch(id);
  }

  Future<Pitch> create({required String name}) async {
    if (!_auth.isAuthenticated) {
      throw StateError('User not authenticated');
    }
    final now = DateTime.now();
    final pitch = Pitch(
      id: _newId(),
      name: name.trim(),
      createdAt: now,
      updatedAt: now,
      calibration: null,
    );

    await _firestore.savePitch(pitch);
    return pitch;
  }

  Future<Pitch> update(Pitch pitch) async {
    if (!_auth.isAuthenticated) {
      throw StateError('User not authenticated');
    }
    await _firestore.updatePitch(pitch);
    return pitch;
  }

  Future<void> delete(String id) async {
    if (!_auth.isAuthenticated) {
      throw StateError('User not authenticated');
    }
    await _firestore.deletePitch(id);
  }

  static CalibrationConfig defaultCalibration() => CalibrationConfig.defaults();

  String _newId() {
    final now = DateTime.now().microsecondsSinceEpoch;
    final rand = Random().nextInt(1 << 32);
    return '$now-$rand';
  }
}

