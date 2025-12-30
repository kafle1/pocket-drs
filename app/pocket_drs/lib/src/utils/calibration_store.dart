// Deprecated: legacy SharedPreferences-based calibration persistence.
//
// Calibration is now stored per-pitch in Firestore (see PitchStore/FirestoreService)
// and the backend is the source of truth for analysis output.
//
// This file is intentionally left as a stub to prevent accidental reuse.
// Do not add new dependencies on it.

@Deprecated('CalibrationStore is removed. Use Firestore-backed pitch documents instead.')
class CalibrationStore {
  CalibrationStore();

  Never _removed() => throw UnsupportedError(
        'CalibrationStore has been removed. Use Firestore-backed pitch documents instead.',
      );

  Future<Object> loadOrDefault() async => _removed();
  Future<void> save(Object _) async => _removed();
  Future<void> clear() async => _removed();
}
