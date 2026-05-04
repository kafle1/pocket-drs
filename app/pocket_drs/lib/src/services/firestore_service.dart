import 'package:cloud_firestore/cloud_firestore.dart';
import '../models/analysis_record.dart';
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

  CollectionReference<Map<String, dynamic>> get _userAnalyses {
    if (_userId == null) throw StateError('User not authenticated');
    return _firestore.collection('users').doc(_userId).collection('analyses');
  }

  /// Latest analyses, newest first, optionally filtered to a single pitch.
  Stream<List<AnalysisRecord>> watchAnalyses({String? pitchId, int limit = 100}) {
    Query<Map<String, dynamic>> q = _userAnalyses.orderBy('createdAt', descending: true).limit(limit);
    if (pitchId != null) {
      q = _userAnalyses
          .where('pitchId', isEqualTo: pitchId)
          .orderBy('createdAt', descending: true)
          .limit(limit);
    }
    return q.snapshots().map((snap) {
      final out = <AnalysisRecord>[];
      for (final d in snap.docs) {
        final r = AnalysisRecord.fromFirestore(d.id, d.data());
        if (r != null) out.add(r);
      }
      return out;
    });
  }

  Future<AnalysisRecord?> getAnalysis(String id) async {
    final d = await _userAnalyses.doc(id).get();
    if (!d.exists) return null;
    return AnalysisRecord.fromFirestore(d.id, d.data() ?? const {});
  }

  Future<void> deleteAnalysis(String id) async {
    await _userAnalyses.doc(id).delete();
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
