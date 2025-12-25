enum VideoSource {
  import,
  record,
}

extension VideoSourceWire on VideoSource {
  /// Server wire value for `CreateJobRequest.video.source`.
  String get wireValue => switch (this) {
        VideoSource.import => 'import',
        VideoSource.record => 'record',
      };
}
