import 'package:cloud_firestore/cloud_firestore.dart';
import '../models/pitch.dart';
import 'auth_service.dart';

class FirestoreService {
  final FirebaseFirestore _firestore = FirebaseFirestore.instance;
  final AuthService _auth;

  FirestoreService(this._auth);

  String? get _userId => _auth.userId;

  CollectionReference<Map<String, dynamic>> get _userPitches {
    if (_userId == null) throw StateError('User not authenticated');
    return _firestore.collection('users').doc(_userId).collection('pitches');
  }

  Future<void> savePitch(Pitch pitch) async {
    await _userPitches.doc(pitch.id).set(pitch.toJson());
  }

  Future<void> updatePitch(Pitch pitch) async {
    await _userPitches.doc(pitch.id).update(pitch.toJson());
  }

  Future<void> deletePitch(String pitchId) async {
    await _userPitches.doc(pitchId).delete();
  }

  Future<Pitch?> getPitch(String pitchId) async {
    final doc = await _userPitches.doc(pitchId).get();
    if (!doc.exists) return null;
    return Pitch.fromJson({...doc.data()!, 'id': doc.id});
  }

  Stream<List<Pitch>> watchPitches() {
    return _userPitches
        .orderBy('updatedAt', descending: true)
        .snapshots()
        .map((snapshot) => snapshot.docs
            .map((doc) => Pitch.fromJson({...doc.data(), 'id': doc.id}))
            .toList());
  }

  Future<List<Pitch>> getPitches() async {
    final snapshot = await _userPitches.orderBy('updatedAt', descending: true).get();
    return snapshot.docs
        .map((doc) => Pitch.fromJson({...doc.data(), 'id': doc.id}))
        .toList();
  }
}
