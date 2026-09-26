import AVFoundation
import Flutter
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    GeneratedPluginRegistrant.register(with: self)
    let controller = window?.rootViewController as! FlutterViewController
    FlutterMethodChannel(name: "pocket_drs/native", binaryMessenger: controller.binaryMessenger)
      .setMethodCallHandler { call, result in
        switch call.method {
        case "trim":
          AppDelegate.trim(call.arguments as! [String: Any], result)
        case "keepScreenOn":
          UIApplication.shared.isIdleTimerDisabled = call.arguments as? Bool ?? false
          result(nil)
        case "freeBytes":
          let attrs = try? FileManager.default.attributesOfFileSystem(forPath: NSTemporaryDirectory())
          result((attrs?[.systemFreeSize] as? NSNumber)?.int64Value ?? 0)
        default:
          result(FlutterMethodNotImplemented)
        }
      }
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  /// Copies the video track between startMs and endMs without re-encoding; returns where that window sits in the clip, in ms.
  private static func trim(_ args: [String: Any], _ result: @escaping FlutterResult) {
    let asset = AVURLAsset(url: URL(fileURLWithPath: args["input"] as! String))
    let output = URL(fileURLWithPath: args["output"] as! String)
    let fail = { (message: String) in
      try? FileManager.default.removeItem(at: output)
      DispatchQueue.main.async { result(FlutterError(code: "trim", message: message, details: nil)) }
    }
    let range = CMTimeRange(
      start: CMTime(value: CMTimeValue(args["startMs"] as! Int), timescale: 1000),
      end: CMTimeMinimum(CMTime(value: CMTimeValue(args["endMs"] as! Int), timescale: 1000), asset.duration))
    guard range.duration > .zero, let track = asset.tracks(withMediaType: .video).first else {
      return fail("The clip is too short.")
    }
    let composition = AVMutableComposition()
    guard
      let copy = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid),
      (try? copy.insertTimeRange(range, of: track, at: .zero)) != nil,
      let export = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetPassthrough)
    else { return fail("Could not cut the clip.") }
    copy.preferredTransform = track.preferredTransform
    export.outputURL = output
    export.outputFileType = .mp4
    export.exportAsynchronously {
      guard export.status == .completed else {
        return fail(export.error?.localizedDescription ?? "Could not cut the clip.")
      }
      DispatchQueue.main.async { result([0, max(1, Int(range.duration.seconds * 1000))]) }
    }
  }
}
