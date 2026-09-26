import 'dart:async';
import 'dart:io';
import 'dart:math';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

import '../analysis/frame_decoder.dart';
import '../api/analysis_result.dart';
import '../api/pocket_drs_api.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../utils/app_settings.dart';
import '../widgets/image_marker.dart';
import 'analyze_screen.dart';

const _native = MethodChannel('pocket_drs/native');
const _clipMs = 4000;
const _rollover = Duration(seconds: 120);
// one full 120 s recording at 8 Mbps is about 120 MB
const _minFreeBytes = 150 << 20;
const _storageFull = 'Phone storage is full. Free some space, then try again.';

/// Tripod session: calibrate once on a short clip, then every BALL press or
/// volume key cuts the last 4 s of the running recording and sends it off.
class SessionScreen extends StatefulWidget {
  const SessionScreen({super.key});

  @override
  State<SessionScreen> createState() => _SessionScreenState();
}

enum _Phase { preview, marking, running }

enum _BallState { uploading, analysing, failed, done }

class _Ball {
  _Ball(this.number, this.hand);
  final int number;
  final String hand;
  String? clip;
  // the 4 s window inside the cut clip, which can open a keyframe early
  int startMs = 0;
  int endMs = 0;
  _BallState state = _BallState.uploading;
  String? error;
  bool canRetry = false;
  String? jobId;
  AnalysisResult? result;
}

class _SessionScreenState extends State<SessionScreen>
    with WidgetsBindingObserver {
  final _api = PocketDrsApi(baseUrl: kServerUrl);
  late final Future<Directory> _dir = _prepareDir();
  final _balls = <_Ball>[];
  final _clock = Stopwatch();
  CameraController? _camera;
  String? _cameraError;
  // the android plugin disposes whichever camera is current, so opens and closes must never overlap
  Future<void> _lifecycle = Future.value();
  // an init that timed out can still finish, and disposing it then would close whichever camera is current
  (CameraController, Future<void>)? _pending;
  Future<void>? _op;
  bool _away = false;
  _Phase _phase = _Phase.preview;
  Uint8List? _frame;
  List<Offset>? _stumps;
  String _hand = 'right';
  Timer? _roll;
  DeviceOrientation? _orientation;
  int _count = 0;
  SpeedUnit _unit = SpeedUnit.kmh;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _native.setMethodCallHandler((call) async {
      if (call.method == 'mark') _mark();
    });
    _openCamera();
    AppSettings.getSpeedUnit().then((u) {
      if (mounted) setState(() => _unit = u);
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _native.setMethodCallHandler(null);
    _native.invokeMethod('keepScreenOn', false);
    _closeCamera();
    if (_pending case (final c, final init)) {
      unawaited(init.then((_) {}, onError: (_) {}).whenComplete(c.dispose));
    }
    _lifecycle.whenComplete(() async {
      _api.close();
      try {
        await (await _dir).delete(recursive: true);
      } catch (_) {}
    });
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // hidden, not inactive: the permission dialog only makes the app inactive
    if (state == AppLifecycleState.hidden && !_away) {
      setState(() {
        _away = true;
        _closeCamera();
      });
    } else if (state == AppLifecycleState.resumed && _away) {
      _away = false;
      _openCamera();
    }
  }

  Future<Directory> _prepareDir() async {
    final tmp = await getTemporaryDirectory();
    final docs = await getApplicationDocumentsDirectory();
    // raw recordings and clips left behind if the app was killed mid-session
    for (final d in [tmp, Directory('${docs.path}/camera/videos')]) {
      if (!await d.exists()) continue;
      await for (final f in d.list()) {
        final name = f.path.split('/').last;
        if (f is File && name.startsWith('REC') ||
            f is Directory && name.startsWith('session')) {
          try {
            await f.delete(recursive: true);
          } on FileSystemException {
            // a session still closing may delete its own folder first
          }
        }
      }
    }
    // a fresh name each time, so a session still closing can't delete this one's clips
    return tmp.createTemp('session');
  }

  void _openCamera() =>
      _lifecycle = _lifecycle.then((_) => _open()).catchError((_) {});

  void _closeCamera() {
    final c = _camera;
    _camera = null;
    _roll?.cancel();
    _lifecycle = _lifecycle.then((_) => _close(c)).catchError((_) {});
  }

  Future<void> _open() async {
    if (!mounted || _away || _camera != null) return;
    setState(() => _cameraError = null);
    try {
      await _dir;
      if (_pending == null) {
        final back = (await availableCameras())
            .where((d) => d.lensDirection == CameraLensDirection.back)
            .firstOrNull;
        if (back == null) {
          throw CameraException('NoCamera', 'This phone has no back camera.');
        }
        final c = CameraController(
          back,
          ResolutionPreset.veryHigh,
          enableAudio: false,
          fps: 60,
          videoBitrate: 8000000,
        );
        _pending = (c, c.initialize());
      }
      final (c, init) = _pending!;
      try {
        // a camera held by another app never finishes initialising on android, so a retry waits on the same one
        await init.timeout(const Duration(seconds: 15));
      } on TimeoutException {
        rethrow;
      } catch (_) {
        _pending = null;
        await c.dispose();
        rethrow;
      }
      _pending = null;
      if (!mounted || _away) return await c.dispose();
      _camera = c;
      if (_orientation != null) await c.lockCaptureOrientation(_orientation);
      setState(() {});
      if (_phase == _Phase.running && !c.value.isRecordingVideo) {
        await _camOp(_record);
      }
    } catch (e) {
      if (mounted) setState(() => _cameraError = _describe(e));
    }
  }

  Future<void> _close(CameraController? c) async {
    if (c == null) return;
    await _op;
    try {
      if (c.value.isRecordingVideo) {
        File((await c.stopVideoRecording()).path).delete().ignore();
      }
    } catch (_) {}
    await c.dispose();
  }

  /// Runs one camera step at a time; a press that lands mid-step is dropped.
  Future<void> _camOp(Future<void> Function(CameraController) f) async {
    final c = _camera;
    if (c == null || _op != null || !mounted) return;
    final done = Completer<void>();
    setState(() => _op = done.future);
    try {
      await f(c);
    } catch (e) {
      if (mounted) setState(() => _cameraError = _describe(e));
    } finally {
      _op = null;
      done.complete();
      if (mounted) setState(() {});
    }
  }

  Future<void> _record(CameraController c) async {
    final free = await _native.invokeMethod<int>('freeBytes');
    if (free! < _minFreeBytes) throw StateError(_storageFull);
    await c.startVideoRecording();
    _clock
      ..reset()
      ..start();
    _roll?.cancel();
    _roll = Timer(_rollover, _rollOver);
  }

  void _rollOver() => _camOp((c) async {
    if (!c.value.isRecordingVideo) return;
    File((await c.stopVideoRecording()).path).delete().ignore();
    if (_camera == c) await _record(c);
  });

  void _busy() => ScaffoldMessenger.of(context).showSnackBar(
    const SnackBar(content: Text('Camera busy, press Ball again')),
  );

  void _calibrate() => _camOp((c) async {
    // clips must keep the rotation the stumps were marked in
    _orientation = c.value.deviceOrientation;
    await c.lockCaptureOrientation(_orientation);
    await c.startVideoRecording();
    await Future<void>.delayed(const Duration(seconds: 1));
    final raw = await c.stopVideoRecording();
    try {
      final jpg = await decodeFrameJpeg(
        videoPath: raw.path,
        timeMs: 500,
        quality: 95,
      );
      if (jpg == null) {
        throw StateError('Could not read a frame from the camera. Try again.');
      }
      if (mounted) {
        setState(() {
          _frame = jpg;
          _phase = _Phase.marking;
        });
      }
    } finally {
      File(raw.path).delete().ignore();
    }
  });

  void _start(List<Offset> stumps) {
    setState(() {
      _stumps = stumps;
      _phase = _Phase.running;
    });
    _native.invokeMethod('keepScreenOn', true);
    _camOp(_record);
  }

  void _mark() {
    if (_op != null) return _busy();
    _camOp((c) async {
      if (_phase != _Phase.running || !c.value.isRecordingVideo) return;
      final endMs = _clock.elapsedMilliseconds;
      final b = _Ball(++_count, _hand);
      setState(() => _balls.insert(0, b));
      final XFile raw;
      try {
        raw = await c.stopVideoRecording();
      } catch (e) {
        _fail(b, _describe(e));
        rethrow;
      }
      unawaited(_cut(b, raw.path, endMs));
      if (_camera == c) await _record(c);
    });
  }

  Future<void> _cut(_Ball b, String raw, int endMs) async {
    if (endMs < _clipMs) {
      File(raw).delete().ignore();
      _fail(
        b,
        'Recording restarted just then, so this ball was cut short. '
        'Bowl it again.',
      );
      return;
    }
    final out = '${(await _dir).path}/ball_${b.number}.mp4';
    try {
      final span = await _native.invokeListMethod<int>('trim', {
        'input': raw,
        'output': out,
        'startMs': max(0, endMs - _clipMs),
        'endMs': endMs,
      });
      b
        ..clip = out
        ..startMs = span![0]
        ..endMs = span[1];
    } catch (e) {
      _fail(b, 'Could not cut the clip: ${_describe(e)}');
      return;
    } finally {
      File(raw).delete().ignore();
    }
    if (!_live(b)) return File(out).delete().ignore();
    await _send(b);
  }

  Future<void> _send(_Ball b) async {
    setState(
      () => b
        ..state = _BallState.uploading
        ..canRetry = false,
    );
    try {
      b.jobId = await _api.createJob(
        videoBytes: await File(b.clip!).readAsBytes(),
        videoFilename: 'ball_${b.number}.mp4',
        requestJson: jobRequest(
          stumps: _stumps!,
          handedness: b.hand,
          startMs: b.startMs,
          endMs: b.endMs,
          maxFrames: 240,
          pitchLengthM: await AppSettings.getPitchLength(),
        ),
      );
    } catch (e) {
      _fail(b, _describe(e), retry: true);
      return;
    }
    if (!_live(b)) return;
    setState(() => b.state = _BallState.analysing);
    try {
      final r = await _api.waitForResult(b.jobId!, cancelled: () => !_live(b));
      if (_live(b)) {
        setState(
          () => b
            ..result = r
            ..state = _BallState.done,
        );
      }
    } catch (e) {
      // a dropped connection is worth another go; a verdict the server refused is not
      _fail(b, _describe(e), retry: e is ApiException);
    }
  }

  // the first job is often still queued or running server-side, so retry
  // resumes polling it instead of uploading a duplicate into the queue
  Future<void> _retry(_Ball b) async {
    final jobId = b.jobId;
    if (jobId == null) return _send(b);
    setState(
      () => b
        ..state = _BallState.analysing
        ..canRetry = false,
    );
    try {
      final r = await _api.waitForResult(jobId, cancelled: () => !_live(b));
      if (_live(b)) {
        setState(
          () => b
            ..result = r
            ..state = _BallState.done,
        );
      }
    } catch (e) {
      if (!_live(b)) return;
      // the job is gone server-side, so there is nothing left to resume
      final dead = e is ApiException && e.statusCode == 404;
      if (dead) return _send(b);
      _fail(b, _describe(e), retry: e is ApiException);
    }
  }

  bool _live(_Ball b) => mounted && _balls.contains(b);

  void _fail(_Ball b, String error, {bool retry = false}) {
    if (!_live(b)) return;
    setState(
      () => b
        ..state = _BallState.failed
        ..error = error
        ..canRetry = retry,
    );
  }

  void _dismiss(_Ball b) {
    setState(() => _balls.remove(b));
    if (b.clip != null) File(b.clip!).delete().ignore();
  }

  String _describe(Object e) {
    if ('$e'.contains('ENOSPC') || '$e'.contains('No space left')) {
      return _storageFull;
    }
    return switch (e) {
      CameraException(
        code: 'CameraAccessDenied' ||
            'CameraAccessDeniedWithoutPrompt' ||
            'CameraAccessRestricted',
      ) =>
        'Camera access is off. Allow it for Pocket DRS in system settings, '
            'then try again.',
      CameraException e => e.description ?? e.code,
      PlatformException e => e.message ?? e.code,
      StateError e => e.message,
      ApiException e => e.message,
      FormatException _ => 'Got an unexpected reply. Try again in a minute.',
      TimeoutException _ =>
        'The camera did not start. Close any other app using it, then try '
            'again.',
      _ => 'Something went wrong. Try again.',
    };
  }

  Future<bool> _confirmLeave() async {
    final leave = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Leave session?'),
        content: const Text('The results here will be lost.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Stay'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Leave'),
          ),
        ],
      ),
    );
    return leave ?? false;
  }

  void _openResult(_Ball b) => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (context) => Scaffold(
        backgroundColor: AppColors.video,
        body: ResultsView(
          videoPath: b.clip!,
          result: b.result!,
          jobId: b.jobId!,
          action: SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: () => Navigator.pop(context),
              icon: const Icon(Icons.arrow_back),
              label: const Text('Back to session'),
            ),
          ),
        ),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (_phase == _Phase.marking) {
      return PopScope(
        canPop: false,
        onPopInvokedWithResult: (_, _) =>
            setState(() => _phase = _Phase.preview),
        child: Scaffold(
          body: SafeArea(
            child: Column(
              children: [
                Row(
                  children: [
                    IconButton(
                      onPressed: () => setState(() => _phase = _Phase.preview),
                      icon: const Icon(Icons.arrow_back),
                      tooltip: 'Back',
                    ),
                    Expanded(
                      child: Text(
                        'Mark the stumps',
                        style: theme.textTheme.titleLarge,
                      ),
                    ),
                  ],
                ),
                Expanded(
                  child: StumpMarker(frame: _frame!, onComplete: _start),
                ),
              ],
            ),
          ),
        ),
      );
    }
    final landscape =
        MediaQuery.orientationOf(context) == Orientation.landscape;
    return PopScope(
      canPop: _balls.isEmpty,
      onPopInvokedWithResult: (didPop, result) async {
        if (didPop) return;
        if (await _confirmLeave() && context.mounted) {
          Navigator.of(context).pop();
        }
      },
      child: Scaffold(
        body: SafeArea(
          child: Flex(
            direction: landscape ? Axis.horizontal : Axis.vertical,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                flex: 3,
                child: ColoredBox(
                  color: AppColors.video,
                  child: _preview(theme),
                ),
              ),
              Expanded(flex: 2, child: _panel(theme)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _preview(ThemeData theme) {
    final c = _camera;
    if (_cameraError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                _cameraError!,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: AppColors.onVideo,
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              FilledButton.icon(
                onPressed: () {
                  setState(_closeCamera);
                  _openCamera();
                },
                icon: const Icon(Icons.refresh),
                label: const Text('Try again'),
              ),
            ],
          ),
        ),
      );
    }
    if (c == null) return const Center(child: CircularProgressIndicator());
    return Center(child: CameraPreview(c));
  }

  Widget _panel(ThemeData theme) {
    final running = _phase == _Phase.running;
    final ready = _camera != null && _cameraError == null;
    final busy = _op != null;
    final hint = running
        ? 'Press Ball or a volume key right after each delivery. '
              'Swipe a card away to delete it.'
        : 'Stand the phone behind the bowler\'s stumps with both sets '
              'of stumps in view, then tap Mark stumps.';
    final actionLabel = running ? 'Ball' : 'Mark stumps';
    final actionIcon = running
        ? Icons.sports_cricket
        : Icons.center_focus_strong_outlined;
    return ListView(
      padding: const EdgeInsets.all(AppSpacing.lg),
      children: [
        Row(
          children: [
            IconButton(
              onPressed: () => Navigator.maybePop(context),
              icon: const Icon(Icons.arrow_back),
              tooltip: 'Back',
            ),
            Text('Session', style: theme.textTheme.titleLarge),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: 'right', label: Text('Right-handed')),
            ButtonSegment(value: 'left', label: Text('Left-handed')),
          ],
          selected: {_hand},
          onSelectionChanged: (s) => setState(() => _hand = s.first),
        ),
        const SizedBox(height: AppSpacing.md),
        AnimatedSwitcher(
          duration: const Duration(milliseconds: 250),
          child: Text(
            hint,
            key: ValueKey(hint),
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            onPressed: ready && !busy ? (running ? _mark : _calibrate) : null,
            icon: AnimatedSwitcher(
              duration: const Duration(milliseconds: 250),
              child: busy
                  ? const SizedBox.square(
                      key: ValueKey('busy'),
                      dimension: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Icon(actionIcon, key: ValueKey(actionIcon)),
            ),
            label: Text(actionLabel),
          ),
        ),
        for (final b in _balls) _card(b, theme),
      ],
    );
  }

  Widget _card(_Ball b, ThemeData theme) {
    final scheme = theme.colorScheme;
    final brightness = theme.brightness;
    final m = b.result?.metrics;
    final speedValue = _unit == SpeedUnit.kmh ? m?.speedKmh : m?.speedMph;
    final speed = speedValue == null
        ? ''
        : ' · ${speedValue.toStringAsFixed(1)} ${_unit.label}';
    final (status, color) = switch (b.state) {
      _BallState.uploading => ('Uploading', scheme.onSurfaceVariant),
      _BallState.analysing => ('Analysing', scheme.onSurfaceVariant),
      _BallState.failed => (b.error ?? 'Failed', scheme.error),
      _BallState.done => switch (b.result!.lbw?.decision) {
        LbwDecisionKey.out => ('Out$speed', AppColors.out(brightness)),
        LbwDecisionKey.notOut => (
          'Not out$speed',
          AppColors.notOut(brightness),
        ),
        LbwDecisionKey.umpiresCall => (
          "Umpire's call$speed",
          AppColors.umpiresCall(brightness),
        ),
        null => ('No LBW call$speed', scheme.onSurfaceVariant),
      },
    };
    return Dismissible(
      key: ObjectKey(b),
      onDismissed: (_) => _dismiss(b),
      child: Card.filled(
        margin: const EdgeInsets.only(bottom: AppSpacing.sm),
        child: ListTile(
          leading: CircleAvatar(
            backgroundColor: scheme.secondaryContainer,
            foregroundColor: scheme.onSecondaryContainer,
            child: Text('${b.number}'),
          ),
          title: Text('Ball ${b.number}'),
          subtitle: AnimatedSwitcher(
            duration: const Duration(milliseconds: 250),
            child: Text(
              status,
              key: ValueKey(status),
              style: TextStyle(color: color),
            ),
          ),
          trailing: switch (b.state) {
            _BallState.uploading ||
            _BallState.analysing => const SizedBox.square(
              dimension: 24,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            _BallState.failed when b.canRetry => IconButton(
              onPressed: () => _retry(b),
              icon: const Icon(Icons.refresh),
              tooltip: 'Retry',
            ),
            _BallState.done => const Icon(Icons.chevron_right),
            _ => null,
          },
          onTap: b.state == _BallState.done ? () => _openResult(b) : null,
        ),
      ),
    );
  }
}
