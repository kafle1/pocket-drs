import 'package:video_player/video_player.dart';

VideoPlayerController createVideoPlayerController(String videoPath) {
  // picked files arrive on the web as blob: urls
  return VideoPlayerController.networkUrl(Uri.parse(videoPath));
}
