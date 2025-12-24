import 'package:video_player/video_player.dart';

import 'video_controller_factory_impl.dart';

/// Creates a [VideoPlayerController] for a local file path.
///
/// We keep this behind a conditional import so Web builds don't pull in
/// `dart:io`.
VideoPlayerController createVideoPlayerController(String videoPath) {
  return createVideoPlayerControllerImpl(videoPath);
}
