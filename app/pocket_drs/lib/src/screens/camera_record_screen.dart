import 'dart:async';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';

class CameraRecordScreen extends StatefulWidget {
  const CameraRecordScreen({super.key});

  @override
  State<CameraRecordScreen> createState() => _CameraRecordScreenState();
}

class _CameraRecordScreenState extends State<CameraRecordScreen> {
  CameraController? _controller;
  bool _initializing = true;
  bool _recording = false;
  String? _error;
  int _initId = 0;
  
  DateTime? _recordingStartTime;
  Timer? _recordingTimer;
  Duration _recordingDuration = Duration.zero;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    final initId = ++_initId;

    setState(() {
      _initializing = true;
      _error = null;
      _recording = false;
    });

    try {
      // Release any previous controller early to avoid camera resource contention.
      final old = _controller;
      _controller = null;
      if (old != null) {
        try {
          await old.dispose();
        } catch (_) {
          // Ignore; we'll surface the next meaningful error.
        }
      }

      final camStatus = await Permission.camera.request();
      if (!camStatus.isGranted) {
        throw Exception('Camera permission denied');
      }

      // Microphone permission is only required for recording audio with video.
      // Many phones record video with audio by default; request proactively.
      await Permission.microphone.request();

      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        throw Exception('No cameras available');
      }

      // Prefer back camera.
      final cam = cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => cameras.first,
      );

      final controller = CameraController(
        cam,
        ResolutionPreset.high,
        enableAudio: true,
      );
      await controller.initialize();

      // If a newer init started while we were waiting, discard this controller.
      if (!mounted || initId != _initId) {
        await controller.dispose();
        return;
      }

      if (!mounted) return;
      setState(() {
        _controller = controller;
        _initializing = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _initializing = false;
      });
    }
  }

  Future<void> _startRecording() async {
    final c = _controller;
    if (c == null || !c.value.isInitialized || _recording) return;
    setState(() {
      _recording = true;
      _error = null;
      _recordingStartTime = DateTime.now();
      _recordingDuration = Duration.zero;
    });
    _recordingTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted || _recordingStartTime == null) return;
      setState(() {
        _recordingDuration = DateTime.now().difference(_recordingStartTime!);
      });
    });
    try {
      await c.startVideoRecording();
    } catch (e) {
      _recordingTimer?.cancel();
      setState(() {
        _recording = false;
        _error = e.toString();
      });
    }
  }

  Future<void> _stopRecording() async {
    final c = _controller;
    if (c == null || !_recording) return;
    _recordingTimer?.cancel();
    try {
      final file = await c.stopVideoRecording();
      if (!mounted) return;
      Navigator.of(context).pop(file);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _recording = false;
        _error = e.toString();
      });
    }
  }

  @override
  void dispose() {
    _recordingTimer?.cancel();
    _controller?.dispose();
    super.dispose();
  }
  
  String _formatDuration(Duration d) {
    String two(int v) => v.toString().padLeft(2, '0');
    final m = d.inMinutes.remainder(60);
    final s = d.inSeconds.remainder(60);
    return '${two(m)}:${two(s)}';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final controller = _controller;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Record delivery'),
        actions: [
          IconButton(
            tooltip: 'Restart camera',
            onPressed: _initializing ? null : _init,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        child: _initializing
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(
                          'Camera error',
                          style: theme.textTheme.titleLarge,
                        ),
                        const SizedBox(height: 8),
                        Text(_error!),
                        const SizedBox(height: 16),
                        FilledButton(
                          onPressed: _init,
                          child: const Text('Try again'),
                        ),
                      ],
                    ),
                  )
                : Column(
                    children: [
                      Expanded(
                        child: Stack(
                          children: [
                            Container(
                              width: double.infinity,
                              color: Colors.black,
                              child: controller == null
                                  ? const SizedBox.shrink()
                                  : CameraPreview(controller),
                            ),
                            // Recording indicator overlay
                            if (_recording)
                              Positioned(
                                top: 16,
                                left: 0,
                                right: 0,
                                child: Center(
                                  child: Container(
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 16,
                                      vertical: 8,
                                    ),
                                    decoration: BoxDecoration(
                                      color: Colors.black54,
                                      borderRadius: BorderRadius.circular(20),
                                    ),
                                    child: Row(
                                      mainAxisSize: MainAxisSize.min,
                                      children: [
                                        Container(
                                          width: 12,
                                          height: 12,
                                          decoration: const BoxDecoration(
                                            color: Colors.red,
                                            shape: BoxShape.circle,
                                          ),
                                        ),
                                        const SizedBox(width: 8),
                                        Text(
                                          _formatDuration(_recordingDuration),
                                          style: const TextStyle(
                                            color: Colors.white,
                                            fontWeight: FontWeight.bold,
                                            fontSize: 16,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                ),
                              ),
                          ],
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.all(16),
                        child: Row(
                          children: [
                            Expanded(
                              child: OutlinedButton.icon(
                                onPressed: _recording ? null : () => Navigator.of(context).pop(),
                                icon: const Icon(Icons.close),
                                label: const Text('Cancel'),
                              ),
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: FilledButton.icon(
                                onPressed: _recording ? _stopRecording : _startRecording,
                                icon: Icon(_recording ? Icons.stop : Icons.fiber_manual_record),
                                label: Text(_recording ? 'Stop' : 'Record'),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
      ),
    );
  }
}
