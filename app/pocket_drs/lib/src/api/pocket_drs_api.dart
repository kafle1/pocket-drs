import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' show Random;
import 'dart:typed_data';
import 'dart:ui' show Offset;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

import '../account/account.dart';
import 'analysis_result.dart';

// The public server. Override at build time with
// --dart-define=POCKET_DRS_SERVER_URL=https://your-server for local dev.
const String kServerUrl = String.fromEnvironment(
  'POCKET_DRS_SERVER_URL',
  defaultValue: 'https://pocketdrs-saarathi.centralindia.cloudapp.azure.com',
);

/// One analysis request. [stumps] is the 8 normalised stump taps: striker
/// TL, TR, BR, BL then bowler TL, TR, BR, BL.
Map<String, Object?> jobRequest({
  required List<Offset> stumps,
  required String handedness,
  required int startMs,
  required int endMs,
  required int maxFrames,
  required double pitchLengthM,
}) => {
  'segment': {'start_ms': startMs, 'end_ms': endMs},
  'calibration': {
    'stump_quads_norm': [
      for (final p in stumps) {'x': p.dx, 'y': p.dy},
    ],
    // taps alone can't recover scale, so the player's pitch length sets it
    'pitch_dimensions_m': {'width': 3.05, 'length': pitchLengthM},
  },
  'tracking': {'sample_fps': 60, 'max_frames': maxFrames},
  'batsman_handedness': handedness,
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

enum ApiErrorKind { network, timeout, server, badResponse, signIn, usedUp }

const _cantConnect =
    "Can't reach the server. Check your internet, or try again later.";
const _noReply = 'No reply in time. Check your internet, or try again later.';
// caddy answers 502 when the VM is up but the server container isn't
const _serverOff = 'The server is off right now. Try again later.';
const _oddReply =
    'Got an unexpected reply from the server. Try again in a minute.';
const kSignInAgain = 'Please sign in again to keep going.';
const kUsedUp =
    'No free reviews left on this account or this phone. Contact the admin for premium access.';

class ApiException implements Exception {
  final ApiErrorKind kind;
  final String message;
  final int? statusCode;
  ApiException(this.kind, this.message, {this.statusCode});
  @override
  String toString() => message;
}

// only a plain sentence the server wrote for people; raw bodies and error codes stay out of the UI
String _extractDetail(String body) {
  try {
    final decoded = jsonDecode(body);
    if (decoded is Map && decoded['detail'] is String) {
      return decoded['detail'] as String;
    }
  } catch (_) {}
  return '';
}

const _jobGone =
    'This ball is no longer on the server. Results are kept for 24 hours. '
    'Send it again.';

// one place for what each http status means to the player; [jobGone] says a 404 means the job expired
void _throwForStatus(int code, String body, {required bool jobGone}) {
  if (code >= 200 && code < 300) return;
  final (kind, msg) = switch (code) {
    400 => (
      ApiErrorKind.badResponse,
      _detailOr(
        body,
        'The app sent a bad request. Update the app and try again.',
      ),
    ),
    401 => (ApiErrorKind.signIn, kSignInAgain),
    402 => (ApiErrorKind.usedUp, kUsedUp),
    403 => (ApiErrorKind.badResponse, 'Only the admin can do this.'),
    404 when jobGone => (ApiErrorKind.badResponse, _jobGone),
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
    _ => (
      ApiErrorKind.badResponse,
      _detailOr(body, 'Got an unexpected reply from the server. Try again.'),
    ),
  };
  throw ApiException(kind, msg, statusCode: code);
}

String _detailOr(String body, String fallback) {
  final d = _extractDetail(body).trim();
  return d.isEmpty ? fallback : d;
}

// plain words for a failed job, by the server's error code
String _jobErrorMessage(String? code, String? serverMessage) => switch (code) {
  'JOB_TIMEOUT' => 'Checking this ball took too long. Trim the clip closer to the delivery and try again.',
  'INVALID_VIDEO' || 'VIDEO_DECODE_FAILED' =>
    "The server couldn't read this video. Try another clip.",
  'CALIBRATION_DEGENERATE' => "The stump marks don't line up. Mark the tops and bottoms of both sets of stumps again.",
  'INTERNAL_ERROR' =>
    'Something went wrong checking this ball. Try again, or try another clip.',
  _ =>
    (serverMessage == null || serverMessage.trim().isEmpty)
        ? 'Could not check this ball. Try again.'
        : serverMessage.trim(),
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
  // an offline home server never answers the handshake, so fail fast instead of waiting out the upload timeout
  PocketDrsApi({required this.baseUrl, http.Client? client})
    : _client =
          client ??
          (kIsWeb
              ? http.Client()
              : IOClient(
                  HttpClient()..connectionTimeout = const Duration(seconds: 10),
                ));

  final String baseUrl;
  final http.Client _client;

  Uri _u(String path) {
    final b = baseUrl.endsWith('/') ? baseUrl : '$baseUrl/';
    return Uri.parse(b)
        .resolve(path.startsWith('/') ? path.substring(1) : path);
  }

  /// Sends with the sign-in headers. A 401 gets one fresh token; a second one signs the person out.
  Future<(int, String)> _send(
    http.BaseRequest Function() build,
    Duration timeout,
  ) async {
    Future<(int, String)> once(Map<String, String> headers) async {
      final req = build()..headers.addAll(headers);
      try {
        final res = await _client.send(req).timeout(timeout);
        final body = await res.stream.bytesToString().timeout(
          const Duration(seconds: 30),
        );
        return (res.statusCode, body);
      } on IOException {
        throw ApiException(ApiErrorKind.network, _cantConnect);
      } on http.ClientException {
        throw ApiException(ApiErrorKind.network, _cantConnect);
      } on TimeoutException {
        throw ApiException(ApiErrorKind.timeout, _noReply);
      }
    }

    var r = await once(await Account.instance.headers());
    if (r.$1 != 401) return r;
    r = await once(await Account.instance.headers(refresh: true));
    if (r.$1 == 401) await Account.instance.signOut();
    return r;
  }

  Future<String> _get(String path, {int seconds = 15, bool jobGone = false}) async {
    final (code, body) = await _send(
      () => http.Request('GET', _u(path)),
      Duration(seconds: seconds),
    );
    _throwForStatus(code, body, jobGone: jobGone);
    return body;
  }

  Future<String> _json(String method, String path, [Object? payload]) async {
    final (code, body) = await _send(() {
      final req = http.Request(method, _u(path));
      if (payload != null) {
        req.headers['Content-Type'] = 'application/json';
        req.body = jsonEncode(payload);
      }
      return req;
    }, const Duration(seconds: 15));
    _throwForStatus(code, body, jobGone: false);
    return body;
  }

  Future<String> createJob({
    required Uint8List videoBytes,
    required String videoFilename,
    required Map<String, Object?> requestJson,
    required String idempotencyKey,
  }) async {
    // Scale the upload timeout with file size so a large clip on a slow
    // connection doesn't get killed mid-upload; capped at 10 minutes.
    final extraSeconds = (videoBytes.length / (100 * 1024)).ceil();
    final uploadSeconds = 60 + extraSeconds > 600 ? 600 : 60 + extraSeconds;

    // a 401 means the server refused it, so the one resend can't make a second job
    final (code, body) = await _send(
      () => http.MultipartRequest('POST', _u('/v1/jobs'))
        ..headers['Idempotency-Key'] = idempotencyKey
        ..fields['request_json'] = jsonEncode(requestJson)
        ..files.add(
          http.MultipartFile.fromBytes(
            'video_file',
            videoBytes,
            filename: videoFilename.isEmpty ? 'video.mp4' : videoFilename,
          ),
        ),
      Duration(seconds: uploadSeconds),
    );
    if (code == 402) Account.instance.logEvent('trials_used_up');
    _throwForStatus(code, body, jobGone: false);

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
    final body = await _get('/v1/jobs/$jobId', jobGone: true);
    try {
      final decoded = jsonDecode(body);
      if (decoded is! Map) throw const FormatException('not an object');
      return JobStatus.fromJson(decoded.cast<String, Object?>());
    } on FormatException {
      throw ApiException(ApiErrorKind.badResponse, _oddReply);
    }
  }

  Future<AnalysisResult> getJobResult(String jobId) async {
    final body = await _get('/v1/jobs/$jobId/result', seconds: 30, jobGone: true);
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

  /// Polls [jobId] until it finishes and returns a result with a ball track.
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
            // a tracked ball with no call still gets the result screen and its reason
            if (result.overlay?.hasPath != true) {
              Account.instance.logEvent('analysis_completed', {
                'decision': 'none',
              });
              // the server's warnings say why no ball was tracked
              throw StateError(
                result.warnings.isEmpty
                    ? 'No ball found. Check the ball is clearly visible, or '
                          're-mark the stumps.'
                    : result.warnings.join('\n'),
              );
            }
            Account.instance.logEvent('analysis_completed', {
              'decision': switch (result.lbw?.decision) {
                LbwDecisionKey.out => 'out',
                LbwDecisionKey.notOut => 'not_out',
                LbwDecisionKey.umpiresCall => 'umpires_call',
                null => 'none',
              },
            });
            return result;
          } catch (e) {
            if (e is StateError ||
                !_isTransient(e) ||
                ++transient >= maxTransient) {
              rethrow;
            }
            await Future.delayed(_backoff(transient));
          }
        }
      }
      if (status.status == 'failed') {
        Account.instance.logEvent('analysis_failed');
        // a failed job gives its free review back
        unawaited(Account.instance.refreshMe());
        throw JobFailedException(
          status.errorCode,
          _jobErrorMessage(status.errorCode, status.errorMessage),
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

  Future<Map<String, Object?>> _map(String body) async {
    try {
      final d = jsonDecode(body);
      if (d is Map) return d.cast<String, Object?>();
    } on FormatException {
      // falls through to the plain message
    }
    throw ApiException(ApiErrorKind.badResponse, _oddReply);
  }

  Future<List<Map<String, Object?>>> _list(String body, String key) async {
    Object? d;
    try {
      d = jsonDecode(body);
    } on FormatException {
      throw ApiException(ApiErrorKind.badResponse, _oddReply);
    }
    // the server may wrap the list in an object or send it bare
    if (d is Map) d = d[key];
    if (d is! List) throw ApiException(ApiErrorKind.badResponse, _oddReply);
    return [
      for (final e in d)
        if (e is Map) e.cast<String, Object?>(),
    ];
  }

  Future<Me> getMe() async => Me.fromJson(await _map(await _get('/v1/me')));

  String _q(String q) =>
      q.trim().isEmpty ? '' : '?q=${Uri.encodeQueryComponent(q.trim())}';

  Future<List<Map<String, Object?>>> adminUsers(String q) async =>
      _list(await _get('/v1/admin/users${_q(q)}'), 'users');

  Future<List<Map<String, Object?>>> adminDevices(String q) async =>
      _list(await _get('/v1/admin/devices${_q(q)}'), 'devices');

  Future<Map<String, Object?>> adminStats() async =>
      _map(await _get('/v1/admin/stats'));

  Future<void> adminUpdateUser(
    String email, {
    String? plan,
    bool resetUsed = false,
  }) => _json(
    'PUT',
    '/v1/admin/users/${Uri.encodeComponent(email.trim().toLowerCase())}',
    {'plan': ?plan, if (resetUsed) 'reset_used': true},
  );

  Future<void> adminResetDevice(String deviceId) => _json(
    'POST',
    '/v1/admin/devices/${Uri.encodeComponent(deviceId)}/reset',
  );

  void close() => _client.close();
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
    required this.errorMessage,
    this.errorCode,
  });

  final String status;
  final int? pct;
  final String? stage;
  final String? errorMessage;
  final String? errorCode;

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

    String? errorMessage;
    String? errorCode;
    final err = json['error'];
    if (err is Map) {
      final msg = err['message'];
      final code = err['code'];
      if (msg is String) errorMessage = msg;
      if (code is String) errorCode = code;
    }

    return JobStatus(
      status: status,
      pct: pct,
      stage: stage,
      errorMessage: errorMessage,
      errorCode: errorCode,
    );
  }
}
