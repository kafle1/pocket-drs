import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'analysis_result.dart';

enum ApiErrorKind { network, timeout, unauthorized, server, badResponse }

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
    if (decoded is Map && decoded['detail'] is String) return decoded['detail'] as String;
  } catch (_) {}
  return _sliceBody(body);
}

class PocketDrsApi {
  PocketDrsApi({
    required this.baseUrl, 
    http.Client? client,
    this.getAuthToken,
  }) : _client = client ?? http.Client();

  final String baseUrl;
  final http.Client _client;
  final Future<String?> Function()? getAuthToken;

  Future<Map<String, String>> _authHeaders() async {
    if (getAuthToken == null) return const <String, String>{};
    final token = await getAuthToken!();
    if (token == null || token.isEmpty) return const <String, String>{};
    return <String, String>{'Authorization': 'Bearer $token'};
  }

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
    
    // Add Firebase auth token if available
    if (getAuthToken != null) {
      final token = await getAuthToken!();
      if (token != null && token.isNotEmpty) {
        req.headers['Authorization'] = 'Bearer $token';
      }
    }
    
    req.fields['request_json'] = jsonEncode(requestJson);
    req.files.add(
      http.MultipartFile.fromBytes(
        'video_file',
        videoBytes,
        filename: videoFilename.isEmpty ? 'video.mp4' : videoFilename,
      ),
    );

    late http.StreamedResponse res;
    late String body;
    try {
      res = await _client.send(req).timeout(const Duration(seconds: 60));
      body = await res.stream.bytesToString();
    } on SocketException {
      throw ApiException(ApiErrorKind.network, 'Cannot reach server');
    } on TimeoutException {
      throw ApiException(ApiErrorKind.timeout, 'Server did not respond');
    }
    if (res.statusCode == 401) {
      throw ApiException(ApiErrorKind.unauthorized, 'Please sign in again', statusCode: 401);
    }
    if (res.statusCode >= 500) {
      throw ApiException(ApiErrorKind.server, 'Server error (${res.statusCode})', statusCode: res.statusCode);
    }
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw ApiException(ApiErrorKind.badResponse, _extractDetail(body), statusCode: res.statusCode);
    }

    final decoded = jsonDecode(body);
    if (decoded is! Map) throw const FormatException('Invalid create job response');
    final jobId = decoded['job_id'];
    if (jobId is! String || jobId.isEmpty) throw const FormatException('Missing job_id');
    return jobId;
  }

  Future<JobStatus> getJobStatus(String jobId) async {
    late http.Response res;
    try {
      res = await _client
          .get(_u('/v1/jobs/$jobId'), headers: await _authHeaders())
          .timeout(const Duration(seconds: 15));
    } on SocketException {
      throw ApiException(ApiErrorKind.network, 'Cannot reach server');
    } on TimeoutException {
      throw ApiException(ApiErrorKind.timeout, 'Server did not respond');
    }
    if (res.statusCode == 401) {
      throw ApiException(ApiErrorKind.unauthorized, 'Please sign in again', statusCode: 401);
    }
    if (res.statusCode >= 500) {
      throw ApiException(ApiErrorKind.server, 'Server error (${res.statusCode})', statusCode: res.statusCode);
    }
    if (res.statusCode != 200) {
      throw ApiException(ApiErrorKind.badResponse, _extractDetail(res.body), statusCode: res.statusCode);
    }
    final decoded = jsonDecode(res.body);
    if (decoded is! Map) throw const FormatException('Invalid status response');
    return JobStatus.fromJson(decoded.cast<String, Object?>());
  }

  Future<AnalysisResult> getJobResult(String jobId) async {
    late http.Response res;
    try {
      res = await _client
          .get(_u('/v1/jobs/$jobId/result'), headers: await _authHeaders())
          .timeout(const Duration(seconds: 30));
    } on SocketException {
      throw ApiException(ApiErrorKind.network, 'Cannot reach server');
    } on TimeoutException {
      throw ApiException(ApiErrorKind.timeout, 'Server did not respond');
    }
    if (res.statusCode == 401) {
      throw ApiException(ApiErrorKind.unauthorized, 'Please sign in again', statusCode: 401);
    }
    if (res.statusCode >= 500) {
      throw ApiException(ApiErrorKind.server, 'Server error (${res.statusCode})', statusCode: res.statusCode);
    }
    if (res.statusCode != 200) {
      throw ApiException(ApiErrorKind.badResponse, _extractDetail(res.body), statusCode: res.statusCode);
    }
    final decoded = jsonDecode(res.body);
    if (decoded is! Map) throw ApiException(ApiErrorKind.badResponse, 'Invalid result response');
    final status = decoded['status'];
    if (status != 'succeeded') {
      final err = decoded['error'];
      throw ApiException(ApiErrorKind.badResponse, 'Job not succeeded (status=$status, error=$err)');
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
