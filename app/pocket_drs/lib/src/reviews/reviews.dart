import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/widgets.dart';
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
    this.noSignal = false,
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
  // failed for want of a connection, so it goes again by itself once there is one
  bool noSignal;
  // the server's code when it turned the ball away, so the screen can offer the fix
  String? errorCode;
  AnalysisResult? result;
  // live progress while checking, never saved
  int? pct;
  String? stage;
  // place in the server's line, 1 meaning next
  int? queue;
  // share of the clip uploaded so far
  double? sent;
  Completer<void>? _stop;
  // waiting for another ball of this account to finish, since the server runs one at a time;
  // [waitingFor] is that ball when it was sent from this phone
  bool waitingTurn = false;
  Review? waitingFor;

  String get clip => '$dir/clip.mp4';
  String get frame => '$dir/frame.jpg';
  bool get busy =>
      state == ReviewState.sending || state == ReviewState.checking;
  String get handedness => request['batsman_handedness'] as String? ?? 'right';

  Map<String, Object?> get _cal =>
      (request['calibration'] as Map).cast<String, Object?>();

  List<Offset?> get stumps => [
    for (final p in _cal['stump_quads_norm'] as List)
      p is Map
          ? Offset((p['x'] as num).toDouble(), (p['y'] as num).toDouble())
          : null,
  ];

  double get pitchLengthM =>
      (request['pitch_length_m'] as num?)?.toDouble() ?? AppSettings.fullPitchM;

  StumpSize get stumpSize {
    final h = ((_cal['stumps_m'] as Map?)?['height'] as num?)?.toDouble();
    return StumpSize.values.firstWhere(
      (s) => (s.heightM - (h ?? 0)).abs() < 0.001,
      orElse: () => StumpSize.regulation,
    );
  }

  Map<String, Object?> _toJson() => {
    'created_at': createdAt.toIso8601String(),
    'request': request,
    'idem': idem,
    'job_id': jobId,
    'state': state.name,
    'error': error,
    'retryable': retryable,
    'no_signal': noSignal,
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
      noSignal: j['no_signal'] as bool? ?? false,
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
  Reviews._() {
    AppLifecycleListener(onResume: _retryOffline);
  }
  static final instance = Reviews._();
  Timer? _offline;

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
        // never deleted: a half-written folder costs little, a lost review can't come back
        debugPrint('[REVIEWS] skipping ${d.path}: $e');
      }
    }
    if (gen != _gen) return;
    loaded.sort((a, b) => b.createdAt.compareTo(a.createdAt));
    _root = root.path;
    _items.addAll(loaded);
    notifyListeners();
    for (final r in loaded.where((r) => r.busy || r.noSignal)) {
      unawaited(_run(r, gen));
    }
  }

  // every ball that failed for want of signal goes again
  void _retryOffline() {
    _offline?.cancel();
    _offline = null;
    for (final r in _items.where((r) => r.noSignal && !r.busy).toList()) {
      retry(r);
    }
  }

  /// Stops the upload of a ball still being sent; it can be sent again later.
  void cancel(Review r) {
    final stop = r._stop;
    if (stop == null || stop.isCompleted) return;
    stop.complete();
    notifyListeners();
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
  void remark(Review r, List<Offset?> stumps, PitchSetup pitch) {
    if (r.busy) return;
    r
      ..request = {
        ...r.request,
        'calibration': calibrationJson(
          stumps: stumps,
          stumpSize: pitch.stumps,
          frameMs: r._cal['frame_ms'] as int?,
        ),
        'tracking': {'ball_type': pitch.ball.name},
        'pitch_length_m': pitch.lengthM,
      }
      ..jobId = null
      ..idem = newIdempotencyKey()
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
        ..retryable = false
        ..noSignal = false;
      notifyListeners();
    }

    final stop = r._stop = Completer<void>();
    bool stopped() => gone() || stop.isCompleted;

    final api = PocketDrsApi();
    try {
      if (r.jobId == null) {
        set(ReviewState.sending);
        if (await Account.instance.outOfReviews()) {
          throw ApiException(ApiErrorKind.usedUp, kUsedUp);
        }
        final bytes = await File(r.clip).readAsBytes();
        // the server takes one job per account at a time, so balls queue here oldest first
        while (r.jobId == null) {
          final ahead = _items
              .where((o) => o.busy && o.createdAt.isBefore(r.createdAt))
              .toList();
          for (final o in ahead) {
            r
              ..waitingTurn = true
              ..waitingFor = o;
            notifyListeners();
            await _settled(o, stopped);
          }
          r
            ..waitingTurn = false
            ..waitingFor = null;
          if (gone()) return;
          var last = 0.0;
          try {
            r.jobId = await api.createJob(
              videoBytes: bytes,
              videoFilename: 'clip.mp4',
              requestJson: r.request,
              idempotencyKey: r.idem,
              cancel: stop.future,
              onSent: (k) {
                r.sent = k;
                // a redraw every 2 % is smooth enough
                if (k - last < 0.02 && k < 1) return;
                last = k;
                notifyListeners();
              },
            );
          } on ApiException catch (e) {
            if (e.kind != ApiErrorKind.jobInProgress || stop.isCompleted) {
              rethrow;
            }
            r.sent = null;
            if (e.jobId == null) {
              // another upload from this account is still arriving; try again once it has
              r.waitingTurn = true;
              notifyListeners();
              await Future<void>.delayed(const Duration(seconds: 10));
              continue;
            }
            final ours = _items.where((o) => o.jobId == e.jobId).firstOrNull;
            r
              ..waitingTurn = true
              ..waitingFor = ours;
            notifyListeners();
            if (ours != null) {
              await _settled(ours, stopped);
            } else {
              // sent from another phone or the website; only its end matters, not its call
              await api
                  .waitForResult(e.jobId!, cancelled: stopped)
                  .then((_) {}, onError: (_) {});
            }
            // a check that ended fast must not turn this into a tight upload loop
            await Future<void>.delayed(const Duration(seconds: 2));
          }
        }
        if (gone()) return;
        await _save(r);
      }
      set(ReviewState.checking);
      final result = await api.waitForResult(
        r.jobId!,
        cancelled: gone,
        onStatus: (s) {
          r
            ..queue = s.queuePosition
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
      if (stop.isCompleted) {
        r
          ..state = ReviewState.failed
          ..error = 'Sending stopped. Send it again when you are ready.'
          ..retryable = true;
      } else if (e.statusCode == 404 && r.jobId != null) {
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
          ..errorCode = e.code
          // a malformed request or an old app fails the same way every time
          ..retryable =
              e.kind != ApiErrorKind.badResponse &&
              e.kind != ApiErrorKind.outdated
          ..noSignal = e.kind == ApiErrorKind.network;
        if (r.noSignal) {
          _offline ??= Timer(const Duration(seconds: 20), _retryOffline);
        }
      }
    } on JobFailedException catch (e) {
      r
        ..state = ReviewState.failed
        ..error = e.message
        ..errorCode = e.code;
      // the server stopped a slow check and kept the review, so the same clip can go again
      if (e.code == 'TIMED_OUT') {
        r
          ..jobId = null
          ..idem = newIdempotencyKey()
          ..retryable = true;
      }
    } on FileSystemException {
      r
        ..state = ReviewState.failed
        ..error =
            "Couldn't read this ball's clip on the phone. Record it again.";
    } catch (e) {
      // waitForResult stops with a StateError once the review is deleted or the person signs out
      if (gone()) return;
      // anything unforeseen still ends the wait, so no ball hangs on a spinner
      debugPrint('[REVIEWS] run: $e');
      r
        ..state = ReviewState.failed
        ..error = "Couldn't check this ball. Try again."
        ..retryable = true;
    } finally {
      api.close();
      if (identical(r._stop, stop)) r._stop = null;
    }
    if (gone()) return;
    r
      ..sent = null
      ..pct = null
      ..stage = null
      ..queue = null
      ..waitingTurn = false
      ..waitingFor = null;
    notifyListeners();
    await _save(r);
  }

  // done when [o] stops running, is deleted, or the person signs out
  Future<void> _settled(Review o, bool Function() gone) {
    final c = Completer<void>();
    void check() {
      if (o.busy && !gone() && _items.contains(o)) return;
      removeListener(check);
      c.complete();
    }

    addListener(check);
    check();
    return c.future;
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
