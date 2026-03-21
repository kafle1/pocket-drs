import 'dart:math';

import 'package:cloud_firestore/cloud_firestore.dart';

import '../analysis/calibration_config.dart';
import '../models/pitch.dart';
import '../services/auth_service.dart';
import '../services/firestore_service.dart';
import 'local_pitch_store.dart';

class PitchStore {
  PitchStore._(this._auth, this._firestore, this._local);

  factory PitchStore({
    AuthService? authService,
    FirestoreService? firestoreService,
    LocalPitchStore? localPitchStore,
  }) {
    final auth = authService ?? AuthService();
    final firestore = firestoreService ?? FirestoreService(auth);
    final local = localPitchStore ?? LocalPitchStore();
    return PitchStore._(auth, firestore, local);
  }

  final AuthService _auth;
  final FirestoreService _firestore;
  final LocalPitchStore _local;

  Future<List<Pitch>> loadAll() async {
    if (!_auth.isAuthenticated) {
      throw StateError('User not authenticated');
    }
    try {
      final pitches = await _firestore.getPitches();
      await _local.replaceAll(pitches);
      return pitches;
    } on Object catch (e) {
      if (!_shouldFallbackToLocal(e)) rethrow;
      return _local.loadAll();
    }
  }

  Future<Pitch?> loadById(String id) async {
    if (!_auth.isAuthenticated) {
      throw StateError('User not authenticated');
    }
    try {
      final pitch = await _firestore.getPitch(id);
      if (pitch != null) {
        await _local.save(pitch);
      }
      return pitch ?? _local.loadById(id);
    } on Object catch (e) {
      if (!_shouldFallbackToLocal(e)) rethrow;
      return _local.loadById(id);
    }
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

    try {
      await _firestore.savePitch(pitch);
    } on Object catch (e) {
      if (!_shouldFallbackToLocal(e)) rethrow;
    }
    await _local.save(pitch);
    return pitch;
  }

  Future<Pitch> update(Pitch pitch) async {
    if (!_auth.isAuthenticated) {
      throw StateError('User not authenticated');
    }
    try {
      await _firestore.updatePitch(pitch);
    } on Object catch (e) {
      if (!_shouldFallbackToLocal(e)) rethrow;
    }
    await _local.save(pitch);
    return pitch;
  }

  Future<void> delete(String id) async {
    if (!_auth.isAuthenticated) {
      throw StateError('User not authenticated');
    }
    try {
      await _firestore.deletePitch(id);
    } on Object catch (e) {
      if (!_shouldFallbackToLocal(e)) rethrow;
    }
    await _local.delete(id);
  }

  static CalibrationConfig defaultCalibration() => CalibrationConfig.defaults();

  String _newId() {
    final now = DateTime.now().microsecondsSinceEpoch;
    final rand = Random().nextInt(1 << 32);
    return '$now-$rand';
  }

  bool _shouldFallbackToLocal(Object error) {
    if (error is FirebaseException) {
      return error.plugin == 'cloud_firestore' ||
          error.code == 'permission-denied' ||
          error.code == 'unavailable' ||
          error.code == 'not-found';
    }
    return false;
  }
}

