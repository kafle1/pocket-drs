import 'dart:async';
import 'dart:io';
import 'dart:math';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

import '../analysis/frame_decoder.dart';
import '../account/account.dart';
import '../api/analysis_result.dart';
import '../api/pocket_drs_api.dart';
import '../reviews/reviews.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../utils/app_settings.dart';
import '../widgets/account_widgets.dart';
import '../widgets/batter_picker.dart';
import '../widgets/stump_marker.dart';
import 'review_screen.dart';

const _native = MethodChannel('pocket_drs/native');
// a late press still catches the ball, and the server trims the rest
const _clipMs = 10000;
// shorter than this right after a restart, the delivery can't be in it
const _minClipMs = 1500;
const _rollover = Duration(seconds: 120);
// one full 120 s recording at 8 Mbps is about 120 MB
const _minFreeBytes = 150 << 20;
const _storageFull = 'Phone storage is full. Free some space, then try again.';

/// Tripod session: calibrate once on a short clip, then every BALL press or
/// volume key cuts the last 10 s of the running recording and sends it off.
class SessionScreen extends StatefulWidget {
  const SessionScreen({super.key});

  @override
  State<SessionScreen> createState() => _SessionScreenState();
}

enum _Phase { preview, marking, running }

// a ball is a card from the moment Ball is pressed; it becomes a review once its clip is cut and sent
class _Ball {
  _Ball(this.number);
  final int number;
  Review? review;
  String? error;
}

class _SessionScreenState extends State<SessionScreen>
    with WidgetsBindingObserver {
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
  List<Offset?>? _stumps;
  String _hand = 'right';
  Timer? _roll;
  DeviceOrientation? _orientation;
  int _count = 0;
  SpeedUnit _unit = SpeedUnit.kmh;
  // clips still being cut; the session folder waits for them before it goes
  final _cuts = <Future<void>>{};
  bool _marksEdited = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    Reviews.instance.addListener(_onReviews);
    _native.setMethodCallHandler((call) async {
      if (call.method == 'mark') _mark();
    });
    _openCamera();
    AppSettings.getSpeedUnit().then((u) {
      if (mounted) setState(() => _unit = u);
    });
    AppSettings.getHand().then((h) {
      if (mounted) setState(() => _hand = h);
    });
  }

  void _onReviews() => setState(() {});

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _native.setMethodCallHandler(null);
    _native.invokeMethod('keepScreenOn', false);
    _closeCamera();
    if (_pending case (final c, final init)) {
      unawaited(init.then((_) {}, onError: (_) {}).whenComplete(c.dispose));
    }
    Reviews.instance.removeListener(_onReviews);
    final cuts = _cuts.toList();
    _lifecycle.whenComplete(() async {
      await Future.wait(cuts.map((c) => c.catchError((Object _) {})));
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
      final jpg = await decodeFrameJpeg(videoPath: raw.path, timeMs: 500);
      if (jpg == null) {
        throw StateError('Could not read a frame from the camera. Try again.');
      }
      if (mounted) {
        setState(() {
          _frame = jpg;
          _marksEdited = false;
          _phase = _Phase.marking;
        });
      }
    } finally {
      File(raw.path).delete().ignore();
    }
  });

  void _start(List<Offset?> stumps) {
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
      final b = _Ball(++_count);
      setState(() => _balls.insert(0, b));
      final XFile raw;
      try {
        raw = await c.stopVideoRecording();
      } catch (e) {
        _fail(b, _describe(e));
        rethrow;
      }
      final cut = _cut(b, raw.path, endMs);
      _cuts.add(cut);
      unawaited(cut.whenComplete(() => _cuts.remove(cut)));
      if (_camera == c) await _record(c);
    });
  }

  Future<void> _cut(_Ball b, String raw, int endMs) async {
    if (endMs < _minClipMs) {
      File(raw).delete().ignore();
      _fail(
        b,
        'Recording restarted just then, so this ball was cut short. '
        'Bowl it again.',
      );
      return;
    }
    final out = '${(await _dir).path}/ball_${b.number}.mp4';
    final List<int> span;
    try {
      span = (await _native.invokeListMethod<int>('trim', {
        'input': raw,
        'output': out,
        'startMs': max(0, endMs - _clipMs),
        'endMs': endMs,
      }))!;
    } catch (e) {
      debugPrint('[SESSION] trim: $e');
      return _fail(b, "Couldn't cut this ball's clip. Bowl it again.");
    } finally {
      File(raw).delete().ignore();
    }
    if (!_kept(b)) return File(out).delete().ignore();
    // no upload when the server would turn it away
    if (await Account.instance.outOfReviews()) {
      File(out).delete().ignore();
      if (mounted) showUsedUp(context);
      return _fail(b, kUsedUp);
    }
    try {
      final pitch = await AppSettings.getPitchSetup();
      final info = await _native.invokeMapMethod<String, Object?>('videoInfo', {
        'path': out,
      });
      // marked on a separate short recording, so there is no frame in this clip to name
      final r = await Reviews.instance.submit(
        clip: out,
        frame: _frame!,
        request: jobRequest(
          stumps: _stumps!,
          handedness: _hand,
          startMs: span[0],
          endMs: span[1],
          pitch: pitch,
          frameMs: null,
          captureFps: (info?['fps'] as num?)?.toDouble(),
        ),
      );
      if (_live(b)) setState(() => b.review = r);
    } catch (e) {
      debugPrint('[SESSION] submit: $e');
      _fail(b, _describe(e));
    }
  }

  // a ball not swiped away still goes to the reviews after the screen closes
  bool _kept(_Ball b) => _balls.contains(b);
  bool _live(_Ball b) => mounted && _kept(b);

  void _fail(_Ball b, String error) {
    if (_live(b)) setState(() => b.error = error);
  }

  Future<void> _leaveMarking() async {
    if (_marksEdited && !await confirmDropMarks(context)) return;
    if (mounted) setState(() => _phase = _Phase.preview);
  }

  Future<bool> _confirmEnd() async {
    final end = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('End this session?'),
        content: const Text(
          'Balls already sent carry on and show up in your reviews. '
          'Next time you start, you mark the stumps again.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Keep going'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('End session'),
          ),
        ],
      ),
    );
    return end ?? false;
  }

  void _dismiss(_Ball b) {
    setState(() => _balls.remove(b));
    if (b.review case final r?) Reviews.instance.delete(r);
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
      CameraException _ || PlatformException _ || TimeoutException _ =>
        "The camera didn't start. Close any other app using it, then try again.",
      StateError e => e.message,
      ApiException e => e.message,
      JobFailedException e => e.message,
      FileSystemException _ => "Couldn't read this ball's clip. Bowl it again.",
      FormatException _ =>
        'Got an unexpected reply from the server. Try again in a minute.',
      _ => 'Something went wrong. Try again.',
    };
  }

  void _openResult(Review r) => Navigator.of(
    context,
  ).push(MaterialPageRoute<void>(builder: (_) => ReviewScreen(review: r)));

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (_phase == _Phase.marking) {
      return PopScope(
        canPop: false,
        onPopInvokedWithResult: (_, _) => _leaveMarking(),
        child: Scaffold(
          body: SafeArea(
            child: Column(
              children: [
                Row(
                  children: [
                    IconButton(
                      onPressed: _leaveMarking,
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
                  child: StumpMarker(
                    frame: _frame!,
                    actionLabel: 'Start the session',
                    onComplete: _start,
                    onEdited: () => _marksEdited = true,
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }
    final landscape =
        MediaQuery.orientationOf(context) == Orientation.landscape;
    // every ball is kept in the reviews, but leaving a running session drops its stump marks
    return PopScope(
      canPop: _phase != _Phase.running,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop || !await _confirmEnd()) return;
        if (mounted) Navigator.pop(this.context);
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
              'Every ball is also kept in your reviews.'
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
        BatterPicker(
          hand: _hand,
          onChanged: (h) {
            setState(() => _hand = h);
            AppSettings.setHand(h);
          },
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
        const PlanStatus(),
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
        if (_balls.isNotEmpty) const SizedBox(height: AppSpacing.lg),
        for (final b in _balls) _card(b, theme),
      ],
    );
  }

  Widget _card(_Ball b, ThemeData theme) {
    final scheme = theme.colorScheme;
    final r = b.review;
    final result = r?.state == ReviewState.done ? r!.result : null;
    final fill = AppColors.verdict(result?.lbw?.decision);
    final m = result?.metrics;
    final speedValue = _unit == SpeedUnit.kmh ? m?.speedKmh : m?.speedMph;
    final speed = speedValue == null
        ? ''
        : ' · ${speedValue.toStringAsFixed(0)} ${_unit.label}';
    final failed =
        b.error != null ||
        r?.state == ReviewState.failed ||
        r?.state == ReviewState.expired;
    final status = switch (r?.state) {
      _ when b.error != null => b.error!,
      null => 'Cutting the clip',
      ReviewState.sending => 'Sending',
      ReviewState.checking => 'Checking',
      ReviewState.done =>
        result!.hasCall
            ? '${result.lbw!.decision.label}$speed'
            : 'No call, tap to see why',
      _ => r!.error ?? "Wasn't checked",
    };
    return Dismissible(
      key: ObjectKey(b),
      // a ball still being cut has nothing saved yet; one with a review asks first
      confirmDismiss: (_) async =>
          b.review == null || await confirmDeleteReview(context),
      onDismissed: (_) => _dismiss(b),
      child: Card(
        margin: const EdgeInsets.only(bottom: AppSpacing.sm),
        child: ListTile(
          leading: CircleAvatar(
            // the verdict colour fills the ball number, readable at arm's length
            backgroundColor: fill ?? scheme.secondaryContainer,
            foregroundColor: fill == null
                ? scheme.onSecondaryContainer
                : AppColors.onVerdict(fill),
            child: Text('${b.number}'),
          ),
          title: Text('Ball ${b.number}'),
          subtitle: AnimatedSwitcher(
            duration: const Duration(milliseconds: 220),
            child: Text(
              status,
              key: ValueKey(status),
              style: TextStyle(
                color: failed ? scheme.error : scheme.onSurfaceVariant,
              ),
            ),
          ),
          trailing: switch (r?.state) {
            _ when b.error != null => null,
            null ||
            ReviewState.sending ||
            ReviewState.checking => const SizedBox.square(
              dimension: 24,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            _ when r!.retryable => IconButton(
              onPressed: () => Reviews.instance.retry(r),
              icon: const Icon(Icons.refresh),
              tooltip: 'Try again',
            ),
            _ => const Icon(Icons.chevron_right),
          },
          onTap: r == null ? null : () => _openResult(r),
        ),
      ),
    );
  }
}
