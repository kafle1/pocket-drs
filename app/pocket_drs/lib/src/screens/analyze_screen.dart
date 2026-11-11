import 'dart:io';
import 'dart:math' show max;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import '../analysis/frame_decoder.dart';
import '../account/account.dart';
import '../api/pocket_drs_api.dart';
import '../reviews/reviews.dart';
import '../theme/app_spacing.dart';
import '../utils/app_settings.dart';
import '../widgets/account_widgets.dart';
import '../widgets/stump_marker.dart';
import '../widgets/video_frame_selector.dart';
import '../widgets/video_trim_selector.dart';
import 'filming_guide_screen.dart';
import 'review_screen.dart';

const _native = MethodChannel('pocket_drs/native');

// below this the ball jumps too far between frames to follow well
const _minFps = 50.0;
// a frame shift above this share of the width means the phone moved, not just the players
const _maxShake = 0.03;

/// Pick one video, trim it to the delivery, choose a frame, mark both sets of stumps, then send it.
class AnalyzeScreen extends StatefulWidget {
  const AnalyzeScreen({super.key});

  @override
  State<AnalyzeScreen> createState() => _AnalyzeScreenState();
}

enum _Step { upload, trim, frame, stumps }

class _AnalyzeScreenState extends State<AnalyzeScreen> {
  final _picker = ImagePicker();

  _Step _step = _Step.upload;
  XFile? _video;
  Uint8List? _frameBytes;
  int _segmentStartMs = 0;
  int _segmentEndMs = 0;
  int _frameMs = 0;
  // as the phone filmed it; 0 when the file doesn't say
  double _fps = 0;
  // recorded in the app, so it can be deleted once sent when the player wants that
  bool _videoFromCamera = false;
  String _hand = 'right';
  bool _sending = false;

  void _log(String m) => debugPrint(m);

  @override
  void initState() {
    super.initState();
    _recoverLostVideo();
    AppSettings.getHand().then((h) {
      if (mounted) setState(() => _hand = h);
    });
  }

  void _setHand(String h) {
    setState(() => _hand = h);
    AppSettings.setHand(h);
  }

  // android can kill the app while the camera records, so the clip comes back here
  Future<void> _recoverLostVideo() async {
    try {
      final lost = await _picker.retrieveLostData();
      final video = lost.file;
      if (video == null || lost.type != RetrieveType.video) return;
      if (!mounted || _step != _Step.upload) return;
      // it could be a gallery pick too, so never auto-delete it
      await _useVideo(video, fromCamera: false);
    } catch (e) {
      _log('[PICK] lost data: $e');
    }
  }

  Future<void> _useVideo(XFile video, {required bool fromCamera}) async {
    if (!await _clipLooksUsable(video) || !mounted) return;
    setState(() {
      _video = video;
      _videoFromCamera = fromCamera;
      _frameBytes = null;
      _step = _Step.trim;
    });
  }

  // checked on the phone, so a clip the server can't use never costs an upload or a review
  Future<bool> _clipLooksUsable(XFile video) async {
    final Map<String, Object?>? info;
    try {
      info = await _native.invokeMapMethod<String, Object?>('videoInfo', {
        'path': video.path,
      });
    } on PlatformException catch (e) {
      _log('[PICK] videoInfo: ${e.message}');
      _showError("Couldn't read this video. Try another clip.");
      return false;
    }
    final fps = (info?['fps'] as num?)?.toDouble() ?? 0;
    final ms = (info?['durationMs'] as num?)?.toInt() ?? 0;
    _fps = fps;
    if (ms > 0 && ms < 500) {
      _showError(
        'This clip is under half a second, too short to hold a delivery. '
        'Pick one that shows the whole ball.',
      );
      return false;
    }
    if (fps <= 0 || fps >= _minFps || !mounted) return true;
    return _warn(
      'Filmed at ${fps.round()} frames a second',
      'At this speed the ball jumps a long way between frames, so the call '
          'is often unsure or missing. Set the camera to 60 frames a second '
          'for the next clip.',
    );
  }

  // true when the player chooses to go on anyway
  Future<bool> _warn(String title, String body) async {
    final use = await showModalBottomSheet<bool>(
      context: context,
      showDragHandle: true,
      builder: (context) => _WarnSheet(title: title, body: body),
    );
    return use ?? false;
  }

  Future<void> _pickVideo(ImageSource source) async {
    try {
      final video = await _picker.pickVideo(source: source);
      if (video == null || !mounted) return;
      await _useVideo(video, fromCamera: source == ImageSource.camera);
    } on PlatformException catch (e) {
      _log('[PICK] ${e.code}: ${e.message}');
      _showError(switch (e.code) {
        'camera_access_denied' =>
          'Camera access is off. Allow it for Pocket DRS in your phone settings, then try again.',
        'photo_access_denied' || 'storage_access_denied' =>
          'Access to your videos is off. Allow it for Pocket DRS in your phone settings, then try again.',
        'no_available_camera' => 'No camera found on this phone.',
        _ => "Couldn't open this video. Try another clip.",
      });
    } catch (e) {
      _log('[PICK] $e');
      _showError("Couldn't open this video. Try another clip.");
    }
  }

  void _onTrimSelected(Duration start, Duration end) {
    setState(() {
      _segmentStartMs = start.inMilliseconds;
      _segmentEndMs = end.inMilliseconds;
      _step = _Step.frame;
    });
  }

  Future<bool> _onFrameSelected(Duration timestamp) async {
    final video = _video;
    if (video == null) return false;
    try {
      final bytes = await decodeFrameJpeg(
        videoPath: video.path,
        timeMs: timestamp.inMilliseconds,
      );
      _frameMs = timestamp.inMilliseconds;
      if (bytes == null) {
        _showError("Couldn't read a frame from this clip. Try another one.");
        return false;
      }
      // the user went back while the frame was being read
      if (!mounted || _video != video || _step != _Step.frame) return true;
      setState(() {
        _frameBytes = bytes;
        _step = _Step.stumps;
      });
      return true;
    } catch (e, st) {
      _log('[FRAME] extraction failed: $e\n$st');
      _showError("Couldn't read a frame from this clip. Try another one.");
      return false;
    }
  }

  Future<void> _send(List<Offset?> stumps) async {
    final video = _video, frame = _frameBytes;
    if (video == null || frame == null || _sending) return;
    // check before cutting and uploading a clip the server would turn away
    if (await Account.instance.outOfReviews()) {
      if (mounted) showUsedUp(context);
      return;
    }
    if (!mounted) return;
    final answers = await showModalBottomSheet<(OnFieldCall, bool)>(
      context: context,
      showDragHandle: true,
      builder: (_) => const _BallQuestions(),
    );
    if (answers == null || !mounted) return;
    setState(() => _sending = true);
    final shake = await cameraShake(
      videoPath: video.path,
      startMs: _segmentStartMs,
      endMs: _segmentEndMs,
    ).catchError((Object _) => null);
    if (!mounted) return;
    if ((shake ?? 0) > _maxShake &&
        !await _warn(
          'The phone moved during this ball',
          'A moving picture throws the call off, and the server may refuse '
              'it. A tripod, or the phone propped on something solid, fixes it.',
        )) {
      if (mounted) setState(() => _sending = false);
      return;
    }
    if (!mounted) return;
    final nav = Navigator.of(context);
    final cut =
        '${Directory.systemTemp.path}/pocket_drs_cut_'
        '${DateTime.now().microsecondsSinceEpoch}.mp4';
    try {
      final span = await _native.invokeListMethod<int>('trim', {
        'input': video.path,
        'output': cut,
        'startMs': _segmentStartMs,
        'endMs': _segmentEndMs,
      });
      final pitch = await AppSettings.getPitchSetup();
      final review = await Reviews.instance.submit(
        clip: cut,
        frame: frame,
        request: jobRequest(
          stumps: stumps,
          handedness: _hand,
          startMs: span![0],
          endMs: span[1],
          pitch: pitch,
          // the cut starts at span[0], so the marked frame moves with it
          frameMs: max(0, span[0] + _frameMs - _segmentStartMs),
          captureFps: _fps > 0 ? _fps : null,
          call: answers.$1,
          shotPlayed: answers.$2,
        ),
      );
      if (_videoFromCamera && await AppSettings.getAutoDeleteSource()) {
        File(video.path).delete().ignore();
      }
      nav.pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => ReviewScreen(
            review: review,
            onAnother: () => nav.pushReplacement(
              MaterialPageRoute<void>(builder: (_) => const AnalyzeScreen()),
            ),
          ),
        ),
      );
    } catch (e) {
      _log('[ANALYZE] send: $e');
      File(cut).delete().ignore();
      _showError(switch (e) {
        PlatformException _ =>
          "Couldn't cut this clip. Trim it again, or pick another clip.",
        FileSystemException _ =>
          "Couldn't save the clip. Free some space on the phone, then try again.",
        StateError e => e.message,
        _ => "Couldn't send this ball. Try again.",
      });
      if (mounted) setState(() => _sending = false);
    }
  }

  void _back() {
    setState(() {
      switch (_step) {
        case _Step.trim:
          _step = _Step.upload;
          _video = null;
        case _Step.frame:
          _step = _Step.trim;
        case _Step.stumps:
          _step = _Step.frame;
          _frameBytes = null;
        case _Step.upload:
          break;
      }
    });
  }

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(msg),
        duration: const Duration(seconds: 8),
        showCloseIcon: true,
      ),
    );
  }

  String get _title => switch (_step) {
    _Step.upload => 'Check a clip',
    _Step.trim => 'Trim to the delivery',
    _Step.frame => 'Pick a clear frame',
    _Step.stumps => 'Mark the stumps',
  };

  @override
  Widget build(BuildContext context) {
    return PopScope(
      // back steps through the flow, and only leaves it from the first step
      canPop: _step == _Step.upload && !_sending,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && !_sending) _back();
      },
      child: Scaffold(
        appBar: AppBar(
          title: Text(_title),
          bottom: PreferredSize(
            preferredSize: const Size.fromHeight(3),
            child: TweenAnimationBuilder<double>(
              tween: Tween(end: (_step.index + 1) / _Step.values.length),
              duration: const Duration(milliseconds: 300),
              curve: Curves.easeOutCubic,
              builder: (context, v, _) =>
                  LinearProgressIndicator(value: v, minHeight: 3),
            ),
          ),
        ),
        body: Stack(
          children: [
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 220),
              child: KeyedSubtree(key: ValueKey(_step), child: _body()),
            ),
            if (_sending) ...[
              const ModalBarrier(dismissible: false, color: Colors.black38),
              const Center(child: CircularProgressIndicator()),
            ],
          ],
        ),
      ),
    );
  }

  Widget _body() {
    final v = _video;
    return switch (_step) {
      _Step.upload => _UploadStep(onPick: _pickVideo),
      _Step.trim => VideoTrimSelector(
        videoPath: v!.path,
        onTrimSelected: _onTrimSelected,
      ),
      _Step.frame => VideoFrameSelector(
        videoPath: v!.path,
        start: Duration(milliseconds: _segmentStartMs),
        end: Duration(milliseconds: _segmentEndMs),
        onFrameSelected: _onFrameSelected,
      ),
      _Step.stumps => StumpMarker(
        frame: _frameBytes!,
        actionLabel: 'Check this ball',
        onComplete: _send,
        hand: _hand,
        onHand: _setHand,
      ),
    };
  }
}

class _WarnSheet extends StatelessWidget {
  const _WarnSheet({required this.title, required this.body});
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.xl,
          0,
          AppSpacing.xl,
          AppSpacing.lg,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(title, style: theme.textTheme.titleLarge),
            const SizedBox(height: AppSpacing.sm),
            Text(body, style: theme.textTheme.bodyMedium),
            const SizedBox(height: AppSpacing.xl),
            FilledButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Pick another clip'),
            ),
            const SizedBox(height: AppSpacing.sm),
            OutlinedButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Use it anyway'),
            ),
          ],
        ),
      ),
    );
  }
}

/// The two things only the player knows: the umpire's decision and whether a shot was played.
class _BallQuestions extends StatefulWidget {
  const _BallQuestions();

  @override
  State<_BallQuestions> createState() => _BallQuestionsState();
}

class _BallQuestionsState extends State<_BallQuestions> {
  var _call = OnFieldCall.none;
  var _shot = true;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.xl,
          0,
          AppSpacing.xl,
          AppSpacing.lg,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'What did the umpire give?',
              style: theme.textTheme.titleMedium,
            ),
            const SizedBox(height: AppSpacing.sm),
            SegmentedButton<OnFieldCall>(
              expandedInsets: EdgeInsets.zero,
              showSelectedIcon: false,
              segments: [
                for (final c in OnFieldCall.values)
                  ButtonSegment(value: c, label: Text(c.label)),
              ],
              selected: {_call},
              onSelectionChanged: (v) => setState(() => _call = v.first),
            ),
            const SizedBox(height: AppSpacing.lg),
            Text('Played a shot?', style: theme.textTheme.titleMedium),
            const SizedBox(height: AppSpacing.sm),
            SegmentedButton<bool>(
              expandedInsets: EdgeInsets.zero,
              showSelectedIcon: false,
              segments: const [
                ButtonSegment(value: true, label: Text('Yes')),
                ButtonSegment(value: false, label: Text('No')),
              ],
              selected: {_shot},
              onSelectionChanged: (v) => setState(() => _shot = v.first),
            ),
            const SizedBox(height: AppSpacing.xl),
            FilledButton(
              onPressed: () => Navigator.pop(context, (_call, _shot)),
              child: const Text('Check this ball'),
            ),
          ],
        ),
      ),
    );
  }
}

class _UploadStep extends StatelessWidget {
  const _UploadStep({required this.onPick});
  final void Function(ImageSource) onPick;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return SafeArea(
      top: false,
      child: LayoutBuilder(
        builder: (context, box) => SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: ConstrainedBox(
            constraints: BoxConstraints(
              minHeight: box.maxHeight - AppSpacing.lg * 2,
            ),
            child: IntrinsicHeight(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'One clip of one delivery',
                    style: theme.textTheme.headlineSmall,
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    "Filmed from behind the bowler's stumps with both sets of "
                    'stumps in view. You trim it to the ball, then mark the '
                    'stumps on one frame.',
                    style: theme.textTheme.bodyMedium?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
                  ),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: TextButton.icon(
                      onPressed: () => Navigator.of(context).push(
                        MaterialPageRoute<void>(
                          builder: (_) => const FilmingGuideScreen(),
                        ),
                      ),
                      icon: const Icon(Icons.help_outline),
                      label: const Text('How to film'),
                    ),
                  ),
                  const Spacer(),
                  const SizedBox(height: AppSpacing.xl),
                  const PlanStatus(),
                  const SizedBox(height: AppSpacing.xl),
                  FilledButton.icon(
                    icon: const Icon(Icons.videocam_outlined),
                    label: const Text('Record a clip'),
                    onPressed: () => onPick(ImageSource.camera),
                  ),
                  const SizedBox(height: AppSpacing.md),
                  OutlinedButton.icon(
                    icon: const Icon(Icons.video_library_outlined),
                    label: const Text('Choose from phone'),
                    onPressed: () => onPick(ImageSource.gallery),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
