import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' show Random, min;
import 'dart:typed_data';
import 'dart:ui' show Offset;

import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

import '../account/account.dart';
import '../utils/app_settings.dart';
import 'analysis_result.dart';

// The public server. Override at build time with
// --dart-define=POCKET_DRS_SERVER_URL=https://your-server for local dev.
const String kServerUrl = String.fromEnvironment(
  'POCKET_DRS_SERVER_URL',
  defaultValue: 'https://pocketdrs-saarathi.centralindia.cloudapp.azure.com',
);

/// The calibration block of a request. [stumps] is the 8 normalised stump taps, striker
/// TL, TR, BR, BL then bowler TL, TR, BR, BL; one may be null when it can't be seen.
Map<String, Object?> calibrationJson({
  required List<Offset?> stumps,
  required StumpSize stumpSize,
  required int? frameMs,
}) => {
  'stump_quads_norm': [
    for (final p in stumps) p == null ? null : {'x': p.dx, 'y': p.dy},
  ],
  'stumps_m': {'height': stumpSize.heightM, 'width': stumpSize.widthM},
  'frame_ms': ?frameMs,
};

/// What the umpire gave on the field, so a close call can stand as umpire's call.
enum OnFieldCall {
  out('Out'),
  notOut('Not out'),
  none('No umpire');

  const OnFieldCall(this.label);
  final String label;
  String get wire => switch (this) {
    out => 'out',
    notOut => 'not_out',
    none => 'none',
  };
}

/// One analysis request.
Map<String, Object?> jobRequest({
  required List<Offset?> stumps,
  required String handedness,
  required int startMs,
  required int endMs,
  required PitchSetup pitch,
  required int? frameMs,
  required double? captureFps,
  OnFieldCall call = OnFieldCall.none,
  bool shotPlayed = true,
}) => {
  'segment': {'start_ms': startMs, 'end_ms': endMs},
  'calibration': calibrationJson(
    stumps: stumps,
    stumpSize: pitch.stumps,
    frameMs: frameMs,
  ),
  'tracking': {'ball_type': pitch.ball.name},
  'batsman_handedness': handedness,
  'pitch_length_m': pitch.lengthM,
  if (captureFps != null && captureFps > 0 && captureFps <= 1000)
    'capture_fps': captureFps,
  'on_field_call': call.wire,
  'shot_played': shotPlayed,
};

/// A random v4 UUID, made once per clip and sent again on every retry of it.
String newIdempotencyKey() {
  final r = Random.secure();
  final b = List<int>.generate(16, (_) => r.nextInt(256));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  final h = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
  return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-'
      '${h.substring(16, 20)}-${h.substring(20)}';
}

enum ApiErrorKind {
  network,
  timeout,
  server,
  badResponse,
  signIn,
  usedUp,
  jobInProgress,
  outdated,
}

const kCantConnect =
    "Can't reach the server. Check your internet, or try again later.";
const _noReply = 'No reply in time. Check your internet, or try again later.';
// caddy answers 502 when the VM is up but the server container isn't
const _serverOff = 'The server is off right now. Try again later.';
const _oddReply =
    'Got an unexpected reply from the server. Try again in a minute.';
const kSignInAgain = 'Please sign in again to keep going.';
const kUsedUp = "You've used today's free reviews. More come back tomorrow.";
const kOutdated = 'Update Pocket DRS to keep reviewing.';
const kStoreUrl =
    'https://play.google.com/store/apps/details?id=com.pocketdrs.pocket_drs';

class ApiException implements Exception {
  final ApiErrorKind kind;
  final String message;
  final int? statusCode;
  final String? code;
  // the account's job still running, when the server turned a second one away
  final String? jobId;
  ApiException(
    this.kind,
    this.message, {
    this.statusCode,
    this.code,
    this.jobId,
  });
  @override
  String toString() => message;
}

/// The server's error object, `{code, message, ...}`, or empty when the body isn't one.
Map<String, Object?> _error(String body) {
  try {
    final v = jsonDecode(body);
    final e = v is Map ? v['error'] : null;
    return e is Map ? e.cast<String, Object?>() : const {};
  } on FormatException {
    return const {};
  }
}

// one place for what each http status means to the player; the server's own sentence wins when it sent one
void _throwForStatus(int code, String body) {
  if (code >= 200 && code < 300) return;
  final err = _error(body);
  final errCode = err['code'] is String ? err['code'] as String : null;
  final (kind, fallback) = switch (code) {
    400 => (
      ApiErrorKind.badResponse,
      "The clip couldn't be sent. Pick it again and retry.",
    ),
    401 => (ApiErrorKind.signIn, kSignInAgain),
    402 || 429 => (ApiErrorKind.usedUp, kUsedUp),
    403 => (ApiErrorKind.badResponse, 'Only the admin can do this.'),
    409 => (
      ApiErrorKind.jobInProgress,
      'Another of your balls is still being sent or checked. This one goes once it finishes.',
    ),
    426 => (ApiErrorKind.outdated, kOutdated),
    408 => (
      ApiErrorKind.timeout,
      'The upload took too long. Try again on a better connection.',
    ),
    413 => (
      ApiErrorKind.badResponse,
      'This clip is too big to send. Trim it shorter and try again.',
    ),
    502 => (ApiErrorKind.server, _serverOff),
    503 => (
      ApiErrorKind.server,
      'The server is busy. Try this ball again in a minute.',
    ),
    504 => (ApiErrorKind.timeout, _noReply),
    >= 500 => (
      ApiErrorKind.server,
      'Something went wrong on the server. Try again.',
    ),
    _ => (ApiErrorKind.badResponse, _oddReply),
  };
  var message =
      err['message'] is String && (err['message'] as String).isNotEmpty
      ? err['message'] as String
      : fallback;
  if (err['resets_at'] case final num at) {
    message =
        '$message ${whenBack(DateTime.fromMillisecondsSinceEpoch(at.toInt() * 1000))}.';
  }
  throw ApiException(
    kind,
    message,
    statusCode: code,
    code: errCode,
    jobId: err['job_id'] is String ? err['job_id'] as String : null,
  );
}

// the server gives back the free review of a failed check or one with no call
const notCounted = "This one didn't use up a free review.";

// plain words for a failed job by the server's error code; a decode failure's own message is the decoder's raw text
String _jobErrorMessage(String? code, String? serverMessage) => switch (code) {
  'VIDEO_DECODE_FAILED' =>
    "The server couldn't read this video. Try another clip.",
  'TIMED_OUT' =>
    'This clip took too long to check. Trim it to just the delivery and send it again.',
  _ when serverMessage != null && serverMessage.trim().isNotEmpty =>
    serverMessage.trim(),
  _ =>
    'Something went wrong checking this ball. Try again, or try another clip.',
};

/// A job the server finished with an error; retrying the same clip won't help.
class JobFailedException implements Exception {
  JobFailedException(this.code, this.message);
  final String? code;
  final String message;
  @override
  String toString() => message;
}

class PocketDrsApi {
  // no signal fails in 10 s instead of waiting out a long upload timeout
  final http.Client _client = IOClient(
    HttpClient()..connectionTimeout = const Duration(seconds: 10),
  );

  Uri _u(String path) => Uri.parse('$kServerUrl$path');

  /// Sends with the sign-in headers. A 401 gets one fresh token; a second one signs the person out.
  Future<(int, String)> _send(
    http.BaseRequest Function(Future<void> abort) build,
    Duration timeout, {
    bool device = true,
  }) async {
    Future<(int, String)> once(Map<String, String> headers) async {
      // a timeout alone leaves the upload running, so a retry would send the clip twice
      final abort = Completer<void>();
      final req = build(abort.future)..headers.addAll(headers);
      try {
        final res = await _client.send(req).timeout(timeout);
        final body = await res.stream.bytesToString().timeout(
          const Duration(seconds: 30),
        );
        return (res.statusCode, body);
      } on IOException {
        throw ApiException(ApiErrorKind.network, kCantConnect);
      } on http.ClientException {
        throw ApiException(ApiErrorKind.network, kCantConnect);
      } on TimeoutException {
        abort.complete();
        throw ApiException(ApiErrorKind.timeout, _noReply);
      }
    }

    var r = await once(await Account.instance.headers(device: device));
    if (r.$1 != 401) return r;
    r = await once(
      await Account.instance.headers(refresh: true, device: device),
    );
    if (r.$1 == 401) await Account.instance.signOut();
    return r;
  }

  Future<String> _get(String path, {int seconds = 15}) async {
    final (code, body) = await _send(
      (abort) => http.AbortableRequest('GET', _u(path), abortTrigger: abort),
      Duration(seconds: seconds),
    );
    _throwForStatus(code, body);
    return body;
  }

  Future<String> _json(String method, String path, [Object? payload]) async {
    final (code, body) = await _send((abort) {
      final req = http.AbortableRequest(method, _u(path), abortTrigger: abort);
      if (payload != null) {
        req.headers['Content-Type'] = 'application/json';
        req.body = jsonEncode(payload);
      }
      return req;
    }, const Duration(seconds: 15));
    _throwForStatus(code, body);
    return body;
  }

  /// Uploads one clip; [onSent] gets the share sent so far, and completing [cancel] stops it.
  Future<String> createJob({
    required Uint8List videoBytes,
    required String videoFilename,
    required Map<String, Object?> requestJson,
    required String idempotencyKey,
    void Function(double)? onSent,
    Future<void>? cancel,
  }) async {
    // the server's deadline is min(1800, 60 + bytes/25000) s; 30 s more lets its own "took too long" reply land first
    final uploadSeconds = min(1830, 90 + (videoBytes.length / 25000).ceil());

    // a 401 means the server refused it, so the one resend can't make a second job
    final (code, body) = await _send(
      (abort) =>
          http.AbortableMultipartRequest(
              'POST',
              _u('/v1/jobs'),
              abortTrigger: cancel == null
                  ? abort
                  : Future.any([abort, cancel]),
            )
            ..headers['Idempotency-Key'] = idempotencyKey
            ..fields['request_json'] = jsonEncode(requestJson)
            // a known length keeps the content-length header the server requires
            ..files.add(
              http.MultipartFile(
                'video_file',
                _chunks(videoBytes, onSent),
                videoBytes.length,
                filename: videoFilename.isEmpty ? 'video.mp4' : videoFilename,
              ),
            ),
      Duration(seconds: uploadSeconds),
    );
    _throwForStatus(code, body);

    final Object? decoded;
    try {
      decoded = jsonDecode(body);
    } on FormatException {
      throw ApiException(ApiErrorKind.badResponse, _oddReply);
    }
    final jobId = decoded is Map ? decoded['job_id'] : null;
    if (jobId is! String || jobId.isEmpty) {
      throw ApiException(ApiErrorKind.badResponse, _oddReply);
    }
    Account.instance.logEvent('analysis_started');
    unawaited(Account.instance.refreshMe());
    return jobId;
  }

  Future<JobStatus> getJobStatus(String jobId) async {
    final body = await _get('/v1/jobs/$jobId');
    try {
      final decoded = jsonDecode(body);
      if (decoded is! Map) throw const FormatException('not an object');
      return JobStatus.fromJson(decoded.cast<String, Object?>());
    } on FormatException {
      throw ApiException(ApiErrorKind.badResponse, _oddReply);
    }
  }

  Future<AnalysisResult> getJobResult(String jobId) async {
    final body = await _get('/v1/jobs/$jobId/result', seconds: 30);
    final Object? decoded;
    try {
      decoded = jsonDecode(body);
    } on FormatException {
      throw ApiException(ApiErrorKind.badResponse, _oddReply);
    }
    if (decoded is! Map) {
      throw ApiException(
        ApiErrorKind.badResponse,
        'Could not check this ball. Try again.',
      );
    }
    final status = decoded['status'];
    if (status != 'succeeded') {
      throw ApiException(
        ApiErrorKind.badResponse,
        'Could not check this ball. Try again.',
      );
    }
    final result = decoded['result'];
    if (result is! Map) throw ApiException(ApiErrorKind.badResponse, _oddReply);
    try {
      return AnalysisResult.fromServerJson(result.cast<String, Object?>());
    } on FormatException {
      throw ApiException(ApiErrorKind.badResponse, _oddReply);
    } on TypeError {
      throw ApiException(ApiErrorKind.badResponse, _oddReply);
    }
  }

  /// Deletes the account and its reviews on the server; repeating it is harmless.
  Future<void> deleteAccount() async {
    final (code, body) = await _send(
      (abort) =>
          http.AbortableRequest('DELETE', _u('/v1/me'), abortTrigger: abort),
      const Duration(seconds: 30),
      device: false,
    );
    _throwForStatus(code, body);
  }

  /// Polls [jobId] until it finishes and returns its result, a call or the server's reason for none.
  Future<AnalysisResult> waitForResult(
    String jobId, {
    required bool Function() cancelled,
    void Function(JobStatus)? onStatus,
  }) async {
    const maxPolls = 240;
    const maxTransient = 8;
    // queued time doesn't count against maxPolls (the server's own queue
    // decides that), but it still needs a hard ceiling of its own
    const maxQueuedMs = 15 * 60 * 1000;
    var transient = 0;
    var queuedMs = 0;
    var poll = 0;
    var attempt = 0;
    while (poll < maxPolls) {
      if (cancelled()) throw StateError('Cancelled');
      final JobStatus status;
      try {
        status = await getJobStatus(jobId);
      } catch (e) {
        // an expired or forgotten job won't come back, and a bad request won't fix itself
        if (!_isTransient(e)) rethrow;
        if (++transient >= maxTransient) {
          if (e is ApiException && e.statusCode == 502) rethrow;
          throw ApiException(
            ApiErrorKind.network,
            'Lost the connection while checking this ball. Try again.',
          );
        }
        await Future.delayed(_backoff(transient));
        continue;
      }
      if (cancelled()) throw StateError('Cancelled');
      // only consecutive blips abort a job that is still progressing
      transient = 0;
      onStatus?.call(status);
      if (status.status == 'succeeded') {
        // a blip at the finish line must not throw away a finished analysis
        while (true) {
          try {
            final result = await getJobResult(jobId);
            unawaited(Account.instance.refreshMe());
            Account.instance.logEvent('analysis_completed', {
              'decision': result.lbw?.decision?.name ?? 'none',
            });
            return result;
          } catch (e) {
            if (!_isTransient(e) || ++transient >= maxTransient) rethrow;
            await Future.delayed(_backoff(transient));
          }
        }
      }
      if (status.status == 'failed') {
        Account.instance.logEvent('analysis_failed');
        unawaited(Account.instance.refreshMe());
        throw JobFailedException(
          status.errorCode,
          '${_jobErrorMessage(status.errorCode, status.errorMessage)} $notCounted',
        );
      }
      final ms = attempt < 10 ? 500 : (attempt < 30 ? 800 : 1200);
      attempt++;
      await Future.delayed(Duration(milliseconds: ms));
      if (status.status == 'queued') {
        queuedMs += ms;
        if (queuedMs >= maxQueuedMs) break;
        continue;
      }
      poll++;
    }
    throw ApiException(
      ApiErrorKind.timeout,
      'This ball took too long to check. Try again.',
    );
  }

  Map<String, Object?> _map(String body) {
    try {
      final d = jsonDecode(body);
      if (d is Map) return d.cast<String, Object?>();
    } on FormatException {
      // falls through to the plain message
    }
    throw ApiException(ApiErrorKind.badResponse, _oddReply);
  }

  List<Map<String, Object?>> _list(String body, String key) {
    Object? d;
    try {
      d = jsonDecode(body);
    } on FormatException {
      throw ApiException(ApiErrorKind.badResponse, _oddReply);
    }
    if (d is Map) d = d[key];
    if (d is! List) throw ApiException(ApiErrorKind.badResponse, _oddReply);
    return [
      for (final e in d)
        if (e is Map) e.cast<String, Object?>(),
    ];
  }

  Future<Me> getMe() async => Me.fromJson(_map(await _get('/v1/me')));

  String _q(String q) =>
      q.trim().isEmpty ? '' : '?q=${Uri.encodeQueryComponent(q.trim())}';

  Future<List<Map<String, Object?>>> adminUsers(String q) async =>
      _list(await _get('/v1/admin/users${_q(q)}'), 'users');

  Future<Map<String, Object?>> adminStats() async =>
      _map(await _get('/v1/admin/stats'));

  /// The newest 50 reviews, or only [email]'s when given.
  Future<List<Map<String, Object?>>> adminJobs(String? email) async => _list(
    await _get(
      '/v1/admin/jobs'
      '${email == null ? '' : '?email=${Uri.encodeQueryComponent(email)}'}',
    ),
    'jobs',
  );

  Future<void> adminUpdateUser(String email, String plan) => _json(
    'PUT',
    '/v1/admin/users/${Uri.encodeComponent(email.trim().toLowerCase())}',
    {'plan': plan},
  );

  void close() => _client.close();
}

// handed out in pieces so the screen can show how much of the clip has gone
Stream<List<int>> _chunks(
  Uint8List bytes,
  void Function(double)? onSent,
) async* {
  const size = 64 << 10;
  for (var i = 0; i < bytes.length; i += size) {
    final end = min(i + size, bytes.length);
    yield Uint8List.sublistView(bytes, i, end);
    onSent?.call(end / bytes.length);
  }
}

// timeouts, dropped connections and 5xx can pass; anything else is the real answer
bool _isTransient(Object e) =>
    e is ApiException &&
    (e.kind == ApiErrorKind.network ||
        e.kind == ApiErrorKind.timeout ||
        e.kind == ApiErrorKind.server);

// 1, 2, 4, 8 s, then 8 s, so a short outage is ridden out without hammering the server
Duration _backoff(int attempt) =>
    Duration(seconds: 1 << (attempt - 1).clamp(0, 3));

class JobStatus {
  const JobStatus({
    required this.status,
    required this.pct,
    required this.stage,
    this.errorCode,
    this.errorMessage,
    this.queuePosition,
  });

  final String status;
  final int? pct;
  final String? stage;
  final String? errorCode;
  final String? errorMessage;
  // 1 means next in line; absent once it runs
  final int? queuePosition;

  static JobStatus fromJson(Map<String, Object?> json) {
    final status = json['status'];
    if (status is! String) throw const FormatException('Missing status');

    int? pct;
    String? stage;
    final progress = json['progress'];
    if (progress is Map) {
      final p = progress['pct'];
      final s = progress['stage'];
      if (p is num) pct = p.round();
      if (s is String) stage = s;
    }

    final err = json['error'];
    final code = err is Map ? err['code'] : null;
    final message = err is Map ? err['message'] : null;
    return JobStatus(
      status: status,
      pct: pct,
      stage: stage,
      errorCode: code is String ? code : null,
      errorMessage: message is String ? message : null,
      queuePosition: switch (json['queue_position']) {
        final int q when q > 0 => q,
        _ => null,
      },
    );
  }
}
