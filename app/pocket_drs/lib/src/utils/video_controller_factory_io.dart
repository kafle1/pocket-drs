import 'dart:io';

import 'package:video_player/video_player.dart';

VideoPlayerController createVideoPlayerControllerImpl(String videoPath) {
  return VideoPlayerController.file(File(videoPath));
}
