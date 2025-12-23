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

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    setState(() {
      _initializing = true;
      _error = null;
    });

    try {
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
    });
    try {
      await c.startVideoRecording();
    } catch (e) {
      setState(() {
        _recording = false;
        _error = e.toString();
      });
    }
  }

  Future<void> _stopRecording() async {
    final c = _controller;
    if (c == null || !_recording) return;
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
    _controller?.dispose();
    super.dispose();
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
                        child: Container(
                          width: double.infinity,
                          color: Colors.black,
                          child: controller == null
                              ? const SizedBox.shrink()
                              : CameraPreview(controller),
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
