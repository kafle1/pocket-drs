import 'package:video_player/video_player.dart';

VideoPlayerController createVideoPlayerControllerImpl(String videoPath) {
  throw UnsupportedError(
    'Local file video playback is not supported on Web. Run on Android/iOS.',
  );
}
