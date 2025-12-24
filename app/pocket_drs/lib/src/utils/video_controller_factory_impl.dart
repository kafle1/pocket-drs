import 'package:video_player/video_player.dart';

import 'video_controller_factory_io.dart'
    if (dart.library.html) 'video_controller_factory_web.dart' as impl;

VideoPlayerController createVideoPlayerControllerImpl(String videoPath) {
  return impl.createVideoPlayerControllerImpl(videoPath);
}
