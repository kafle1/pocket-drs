import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' show Offset;

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

import '../account/account.dart';
import '../api/analysis_result.dart';
import '../api/pocket_drs_api.dart';
import '../utils/app_settings.dart';

enum ReviewState { sending, checking, done, failed, expired }

/// One ball sent for review, kept on the phone with its clip, the frame its stumps were marked on, and the result.
class Review {
  Review._({
    required this.dir,
    required this.createdAt,
    required this.request,
    required this.idem,
    this.jobId,
    this.state = ReviewState.sending,
    this.error,
    this.retryable = false,
    this.worstMark,
    this.errorCode,
    this.result,
  });

  final String dir;
  final DateTime createdAt;
  Map<String, Object?> request;
  // reused on every resend of this clip, so a lost reply can't spend a second review
  String idem;
  String? jobId;
  ReviewState state;
  String? error;
  bool retryable;
  int? worstMark;
  // the server's code when it failed the job, so the screen knows re-marking can help
  String? errorCode;
  AnalysisResult? result;
  // live progress while checking, never saved
  int? pct;
  String? stage;

  String get clip => '$dir/clip.mp4';
  String get frame => '$dir/frame.jpg';
  bool get busy =>
      state == ReviewState.sending || state == ReviewState.checking;
  String get handedness => request['batsman_handedness'] as String? ?? 'right';

  // the server drops a job a day after its last change, and the 3D page goes with it
  bool get threeDGone =>
      DateTime.now().difference(createdAt) > const Duration(hours: 23);

  List<Offset> get stumps {
    final cal = request['calibration'] as Map<String, Object?>;
    return [
      for (final p in cal['stump_quads_norm'] as List)
        Offset(((p as Map)['x'] as num).toDouble(), (p['y'] as num).toDouble()),
    ];
  }

  Map<String, Object?> _toJson() => {
    'created_at': createdAt.toIso8601String(),
    'request': request,
    'idem': idem,
    'job_id': jobId,
    'state': state.name,
    'error': error,
    'retryable': retryable,
    'worst_mark': worstMark,
    'error_code': errorCode,
    'result': result?.json,
  };

  static Review _fromJson(String dir, Map<String, Object?> j) {
    final result = j['result'];
    return Review._(
      dir: dir,
      createdAt: DateTime.parse(j['created_at'] as String),
      request: (j['request'] as Map).cast<String, Object?>(),
      idem: j['idem'] as String,
      jobId: j['job_id'] as String?,
      state: ReviewState.values.byName(j['state'] as String),
      error: j['error'] as String?,
      retryable: j['retryable'] as bool? ?? false,
      worstMark: j['worst_mark'] as int?,
      errorCode: j['error_code'] as String?,
      result: result is Map
          ? AnalysisResult.fromServerJson(result.cast<String, Object?>())
          : null,
    );
  }
}

/// Every review on this phone for the signed-in person. A review keeps going when its screen
/// closes, and one the app was killed in the middle of picks up again on the next launch.
class Reviews extends ChangeNotifier {
  Reviews._();
  static final instance = Reviews._();

  static const _kept = 100;
  final List<Review> _items = [];
  String? _root;
  // bumped on every sign-in change, so a run for the last person can't land in this list
  int _gen = 0;

  List<Review> get items => List.unmodifiable(_items);

  Future<void> open(String? uid) async {
    final gen = ++_gen;
    _items.clear();
    _root = null;
    notifyListeners();
    if (uid == null) return;
    final root = Directory(
      '${(await getApplicationDocumentsDirectory()).path}/reviews/$uid',
    );
    await root.create(recursive: true);
    final loaded = <Review>[];
    await for (final d in root.list()) {
      if (d is! Directory) continue;
      try {
        final j = jsonDecode(
          await File('${d.path}/review.json').readAsString(),
        );
        loaded.add(
          Review._fromJson(d.path, (j as Map).cast<String, Object?>()),
        );
      } catch (e) {
        // killed between making the folder and saving it, so there is nothing to resume
        debugPrint('[REVIEWS] dropping ${d.path}: $e');
        d.delete(recursive: true).ignore();
      }
    }
    if (gen != _gen) return;
    loaded.sort((a, b) => b.createdAt.compareTo(a.createdAt));
    _root = root.path;
    _items.addAll(loaded);
    notifyListeners();
    for (final r in loaded.where((r) => r.busy)) {
      unawaited(_run(r, gen));
    }
  }

  /// Saves the clip and its marked frame with this review and starts sending it.
  Future<Review> submit({
    required String clip,
    required Uint8List frame,
    required Map<String, Object?> request,
  }) async {
    final root = _root;
    if (root == null) throw StateError('Sign in again to send this ball.');
    final now = DateTime.now();
    final dir = await Directory('$root/${now.microsecondsSinceEpoch}').create();
    final r = Review._(
      dir: dir.path,
      createdAt: now,
      request: request,
      idem: newIdempotencyKey(),
    );
    try {
      await File(clip).rename(r.clip);
    } on FileSystemException {
      // another volume can't take a rename
      await File(clip).copy(r.clip);
      File(clip).delete().ignore();
    }
    await File(r.frame).writeAsBytes(frame);
    // the first save must land, or the next launch would find a folder it can't resume
    await File('${r.dir}/review.json').writeAsString(jsonEncode(r._toJson()));
    _items.insert(0, r);
    for (final old in _items.skip(_kept).where((r) => !r.busy).toList()) {
      delete(old);
    }
    notifyListeners();
    unawaited(_run(r, _gen));
    return r;
  }

  /// Checks the job again, or sends the clip again when the server no longer has it.
  void retry(Review r) {
    if (r.busy) return;
    unawaited(_run(r, _gen));
    // _run marks it busy before its first await, so a kill from here on resumes it
    unawaited(_save(r));
  }

  /// Sends the clip again with new stump marks and the pitch as it is set now.
  void remark(Review r, List<Offset> stumps, PitchSetup pitch) {
    if (r.busy) return;
    r
      ..request = {
        ...r.request,
        'calibration': calibrationJson(
          stumps: stumps,
          pitchLengthM: pitch.lengthM,
          stumpSize: pitch.stumps,
        ),
      }
      ..jobId = null
      ..idem = newIdempotencyKey()
      ..worstMark = null
      ..result = null;
    unawaited(_run(r, _gen));
    unawaited(_save(r));
  }

  void delete(Review r) {
    if (!_items.remove(r)) return;
    notifyListeners();
    Directory(r.dir).delete(recursive: true).ignore();
  }

  /// Every review of the signed-in person, for deleting the account.
  Future<void> deleteAll() async {
    final root = _root;
    _gen++;
    _items.clear();
    notifyListeners();
    if (root != null) await Directory(root).delete(recursive: true);
  }

  Future<void> _run(Review r, int gen) async {
    bool gone() => gen != _gen || !_items.contains(r);
    void set(ReviewState s) {
      r
        ..state = s
        ..error = null
        ..errorCode = null
        ..retryable = false;
      notifyListeners();
    }

    final api = PocketDrsApi();
    try {
      if (r.jobId == null) {
        set(ReviewState.sending);
        // the plan may have changed since the last check, so ask before refusing
        if (Account.instance.me.value?.usedUp ?? false) {
          await Account.instance.refreshMe();
          if (Account.instance.me.value?.usedUp ?? false) {
            throw ApiException(ApiErrorKind.usedUp, kUsedUp);
          }
        }
        final bytes = await File(r.clip).readAsBytes();
        if (gone()) return;
        r.jobId = await api.createJob(
          videoBytes: bytes,
          videoFilename: 'clip.mp4',
          requestJson: r.request,
          idempotencyKey: r.idem,
        );
        if (gone()) return;
        await _save(r);
      }
      set(ReviewState.checking);
      final result = await api.waitForResult(
        r.jobId!,
        cancelled: gone,
        onStatus: (s) {
          r
            ..pct = s.pct
            ..stage = s.stage ?? s.status;
          notifyListeners();
        },
      );
      r
        ..result = result
        ..state = ReviewState.done;
    } on ApiException catch (e) {
      if (gone()) return;
      if (e.statusCode == 404 && r.jobId != null) {
        // the old key would hand back the expired job
        r
          ..jobId = null
          ..idem = newIdempotencyKey()
          ..state = ReviewState.expired
          ..error =
              'The server cleared this ball before its result came back. Send it again.'
          ..retryable = true;
      } else {
        r
          ..state = ReviewState.failed
          ..error = e.message
          // a malformed request fails the same way every time
          ..retryable = e.kind != ApiErrorKind.badResponse;
      }
    } on JobFailedException catch (e) {
      r
        ..state = ReviewState.failed
        ..error = e.message
        ..errorCode = e.code
        ..worstMark = e.worstMark;
    } on FileSystemException {
      r
        ..state = ReviewState.failed
        ..error =
            "Couldn't read this ball's clip on the phone. Record it again.";
    } on StateError {
      // waitForResult stops this way once the review is deleted or the person signs out
      if (gone()) return;
      rethrow;
    } finally {
      api.close();
    }
    if (gone()) return;
    r
      ..pct = null
      ..stage = null;
    notifyListeners();
    await _save(r);
  }

  // written aside then renamed, so a kill mid-write never leaves half a file
  Future<void> _save(Review r) async {
    final tmp = File('${r.dir}/review.json.tmp');
    try {
      await tmp.writeAsString(jsonEncode(r._toJson()));
      await tmp.rename('${r.dir}/review.json');
    } on FileSystemException catch (e) {
      // deleted while it ran, or the phone is full; the next launch resumes from the last save
      debugPrint('[REVIEWS] save: $e');
    }
  }
}
