import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'analysis_result.dart';

class PocketDrsApi {
  PocketDrsApi({required this.baseUrl, http.Client? client}) : _client = client ?? http.Client();

  final String baseUrl;
  final http.Client _client;

  Uri _u(String path) {
    final b = baseUrl.endsWith('/') ? baseUrl : '$baseUrl/';
    return Uri.parse(b).resolve(path.startsWith('/') ? path.substring(1) : path);
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

    final res = await _client.send(req).timeout(const Duration(seconds: 60));
    final body = await res.stream.bytesToString();
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw StateError('Create job failed (${res.statusCode}): $body');
    }

    final decoded = jsonDecode(body);
    if (decoded is! Map) throw const FormatException('Invalid create job response');
    final jobId = decoded['job_id'];
    if (jobId is! String || jobId.isEmpty) throw const FormatException('Missing job_id');
    return jobId;
  }

  Future<JobStatus> getJobStatus(String jobId) async {
    final res = await _client.get(_u('/v1/jobs/$jobId')).timeout(const Duration(seconds: 15));
    if (res.statusCode != 200) {
      throw StateError('Status request failed (${res.statusCode}): ${res.body}');
    }
    final decoded = jsonDecode(res.body);
    if (decoded is! Map) throw const FormatException('Invalid status response');
    return JobStatus.fromJson(decoded.cast<String, Object?>());
  }

  Future<AnalysisResult> getJobResult(String jobId) async {
    final res = await _client.get(_u('/v1/jobs/$jobId/result')).timeout(const Duration(seconds: 30));
    if (res.statusCode != 200) {
      throw StateError('Result request failed (${res.statusCode}): ${res.body}');
    }
    final decoded = jsonDecode(res.body);
    if (decoded is! Map) throw const FormatException('Invalid result response');
    final status = decoded['status'];
    if (status != 'succeeded') {
      final err = decoded['error'];
      throw StateError('Job not succeeded (status=$status, error=$err)');
    }
    final result = decoded['result'];
    if (result is! Map) throw const FormatException('Missing result');
    return AnalysisResult.fromServerJson(result.cast<String, Object?>());
  }

  void close() => _client.close();
}

class JobStatus {
  const JobStatus({required this.status, required this.pct, required this.stage, required this.errorMessage});

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

    return JobStatus(status: status, pct: pct, stage: stage, errorMessage: errorMessage);
  }
}
