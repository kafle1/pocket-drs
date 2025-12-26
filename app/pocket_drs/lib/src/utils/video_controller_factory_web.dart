import 'package:video_player/video_player.dart';

VideoPlayerController createVideoPlayerControllerImpl(String videoPath) {
  // On Flutter Web, picked files typically come through as a blob: URL.
  // VideoPlayerController.networkUrl supports that.
  return VideoPlayerController.networkUrl(Uri.parse(videoPath));
}
