import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' show Offset;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

import 'analysis_result.dart';

// Public, anonymous server. Override at build time with
// --dart-define=POCKET_DRS_SERVER_URL=https://your-server for local dev.
const String kServerUrl = String.fromEnvironment(
  'POCKET_DRS_SERVER_URL',
  defaultValue: 'https://pocket-drs.tailcaa5ff.ts.net',
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

enum ApiErrorKind { network, timeout, server, badResponse }

// the public server is a home Mac, so a dead connection often means it is off rather than the phone
const _cantConnect =
    "Can't reach the server. Check your internet, or try again later.";
const _noReply = 'No reply in time. Check your internet, or try again later.';
// the tunnel answers 502 when the Mac is online but the server on it isn't running
const _serverOff = 'The server is off right now. Try again later.';

class ApiException implements Exception {
  final ApiErrorKind kind;
  final String message;
  final int? statusCode;
  ApiException(this.kind, this.message, {this.statusCode});
  @override
  String toString() => message;
}

String _sliceBody(String body) {
  final stripped = body.replaceAll(RegExp(r'<[^>]*>'), '').trim();
  return stripped.length > 200 ? stripped.substring(0, 200) : stripped;
}

String _extractDetail(String body) {
  try {
    final decoded = jsonDecode(body);
    if (decoded is Map && decoded['detail'] is String) {
      return decoded['detail'] as String;
    }
  } catch (_) {}
  return _sliceBody(body);
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
    return Uri.parse(
      b,
    ).resolve(path.startsWith('/') ? path.substring(1) : path);
  }

  Future<String> createJob({
    required Uint8List videoBytes,
    required String videoFilename,
    required Map<String, Object?> requestJson,
  }) async {
    final req = http.MultipartRequest('POST', _u('/v1/jobs'));

    req.fields['request_json'] = jsonEncode(requestJson);
    req.files.add(
      http.MultipartFile.fromBytes(
        'video_file',
        videoBytes,
        filename: videoFilename.isEmpty ? 'video.mp4' : videoFilename,
      ),
    );

    // Scale the upload timeout with file size so a large clip on a slow
    // connection doesn't get killed mid-upload; capped at 10 minutes.
    final extraSeconds = (videoBytes.length / (100 * 1024)).ceil();
    final uploadSeconds = 60 + extraSeconds > 600 ? 600 : 60 + extraSeconds;

    late http.StreamedResponse res;
    late String body;
    try {
      res = await _client.send(req).timeout(Duration(seconds: uploadSeconds));
      body = await res.stream.bytesToString().timeout(
        const Duration(seconds: 30),
      );
    } on IOException {
      throw ApiException(ApiErrorKind.network, _cantConnect);
    } on http.ClientException {
      throw ApiException(ApiErrorKind.network, _cantConnect);
    } on TimeoutException {
      throw ApiException(ApiErrorKind.timeout, _noReply);
    }
    if (res.statusCode == 502) {
      throw ApiException(ApiErrorKind.server, _serverOff, statusCode: 502);
    }
    if (res.statusCode == 503) {
      throw ApiException(
        ApiErrorKind.server,
        'The server is busy. Try this ball again in a minute.',
        statusCode: 503,
      );
    }
    if (res.statusCode >= 500) {
      throw ApiException(
        ApiErrorKind.server,
        'Something went wrong checking this ball. Try again.',
        statusCode: res.statusCode,
      );
    }
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw ApiException(
        ApiErrorKind.badResponse,
        _extractDetail(body),
        statusCode: res.statusCode,
      );
    }

    final decoded = jsonDecode(body);
    if (decoded is! Map) {
      throw const FormatException('Invalid create job response');
    }
    final jobId = decoded['job_id'];
    if (jobId is! String || jobId.isEmpty) {
      throw const FormatException('Missing job_id');
    }
    return jobId;
  }

  Future<JobStatus> getJobStatus(String jobId) async {
    late http.Response res;
    try {
      res = await _client
          .get(_u('/v1/jobs/$jobId'))
          .timeout(const Duration(seconds: 15));
    } on IOException {
      throw ApiException(ApiErrorKind.network, _cantConnect);
    } on http.ClientException {
      throw ApiException(ApiErrorKind.network, _cantConnect);
    } on TimeoutException {
      throw ApiException(ApiErrorKind.timeout, _noReply);
    }
    if (res.statusCode == 502) {
      throw ApiException(ApiErrorKind.server, _serverOff, statusCode: 502);
    }
    if (res.statusCode >= 500) {
      throw ApiException(
        ApiErrorKind.server,
        'Something went wrong checking this ball. Try again.',
        statusCode: res.statusCode,
      );
    }
    if (res.statusCode == 404) {
      throw ApiException(
        ApiErrorKind.badResponse,
        'The server no longer has this ball, maybe after a restart. Send it again.',
        statusCode: 404,
      );
    }
    if (res.statusCode != 200) {
      throw ApiException(
        ApiErrorKind.badResponse,
        _extractDetail(res.body),
        statusCode: res.statusCode,
      );
    }
    final decoded = jsonDecode(res.body);
    if (decoded is! Map) throw const FormatException('Invalid status response');
    return JobStatus.fromJson(decoded.cast<String, Object?>());
  }

  Future<AnalysisResult> getJobResult(String jobId) async {
    late http.Response res;
    try {
      res = await _client
          .get(_u('/v1/jobs/$jobId/result'))
          .timeout(const Duration(seconds: 30));
    } on IOException {
      throw ApiException(ApiErrorKind.network, _cantConnect);
    } on http.ClientException {
      throw ApiException(ApiErrorKind.network, _cantConnect);
    } on TimeoutException {
      throw ApiException(ApiErrorKind.timeout, _noReply);
    }
    if (res.statusCode == 502) {
      throw ApiException(ApiErrorKind.server, _serverOff, statusCode: 502);
    }
    if (res.statusCode >= 500) {
      throw ApiException(
        ApiErrorKind.server,
        'Something went wrong checking this ball. Try again.',
        statusCode: res.statusCode,
      );
    }
    if (res.statusCode != 200) {
      throw ApiException(
        ApiErrorKind.badResponse,
        _extractDetail(res.body),
        statusCode: res.statusCode,
      );
    }
    final decoded = jsonDecode(res.body);
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
    if (result is! Map) throw const FormatException('Missing result');
    return AnalysisResult.fromServerJson(result.cast<String, Object?>());
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
        // a restarted server has forgotten the job, and polling won't bring it back
        if (e is ApiException && e.statusCode == 404) rethrow;
        if (++transient >= maxTransient) {
          if (e is ApiException && e.statusCode == 502) rethrow;
          throw ApiException(
            ApiErrorKind.network,
            'Lost the connection while checking this ball. Try again.',
          );
        }
        await Future.delayed(const Duration(seconds: 1));
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
              // the server's warnings say why no ball was tracked
              throw StateError(
                result.warnings.isEmpty
                    ? 'No ball found. Check the ball is clearly visible, or '
                          're-mark the stumps.'
                    : result.warnings.join('\n'),
              );
            }
            return result;
          } catch (e) {
            if (e is StateError || ++transient >= maxTransient) rethrow;
            await Future.delayed(const Duration(seconds: 1));
          }
        }
      }
      if (status.status == 'failed') {
        throw StateError(
          status.errorMessage ?? 'Could not check this ball. Try again.',
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

  void close() => _client.close();
}

class JobStatus {
  const JobStatus({
    required this.status,
    required this.pct,
    required this.stage,
    required this.errorMessage,
  });

  final String status;
  final int? pct;
  final String? stage;
  final String? errorMessage;

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
    final err = json['error'];
    if (err is Map) {
      final msg = err['message'];
      if (msg is String) errorMessage = msg;
    }

    return JobStatus(
      status: status,
      pct: pct,
      stage: stage,
      errorMessage: errorMessage,
    );
  }
}
