import 'dart:io';

import 'package:video_player/video_player.dart';

VideoPlayerController createVideoPlayerController(String videoPath) {
  return VideoPlayerController.file(File(videoPath));
}
