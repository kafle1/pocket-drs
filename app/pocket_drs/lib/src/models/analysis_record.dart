/// One persisted analysis: the raw server result envelope plus the IDs that
/// let us trace it back to a job and pitch.  Stored under
/// `users/{uid}/analyses/{auto-id}` by the server when an analysis succeeds.
library;

import '../api/analysis_result.dart';

class AnalysisRecord {
  const AnalysisRecord({
    required this.id,
    required this.jobId,
    required this.pitchId,
    required this.createdAt,
    required this.result,
  });

  /// Firestore document id.
  final String id;
  final String jobId;
  final String? pitchId;
  final DateTime createdAt;
  final AnalysisResult result;

  static AnalysisRecord? fromFirestore(String docId, Map<String, Object?> raw) {
    final res = raw['result'];
    if (res is! Map) return null;
    AnalysisResult parsed;
    try {
      parsed = AnalysisResult.fromServerJson(res.cast<String, Object?>());
    } catch (_) {
      return null;
    }
    final ts = raw['createdAt'];
    DateTime when = DateTime.now();
    if (ts != null) {
      // Firestore Timestamp has a `toDate()` method; we can't import the
      // Firestore SDK here without a circular dep, so call dynamically.
      try {
        final dyn = ts as dynamic;
        final d = dyn.toDate();
        if (d is DateTime) when = d;
      } catch (_) {
        if (ts is String) {
          when = DateTime.tryParse(ts) ?? when;
        }
      }
    }
    return AnalysisRecord(
      id: docId,
      jobId: raw['jobId'] is String ? raw['jobId'] as String : '',
      pitchId: raw['pitchId'] is String ? raw['pitchId'] as String : null,
      createdAt: when,
      result: parsed,
    );
  }
}
