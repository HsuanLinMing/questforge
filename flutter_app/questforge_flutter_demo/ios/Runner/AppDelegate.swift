import UIKit
import Flutter

@main
@objc class AppDelegate: FlutterAppDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {

    let ok = super.application(application, didFinishLaunchingWithOptions: launchOptions)

    // ✅ 改成 super 之後再註冊
    GeneratedPluginRegistrant.register(with: self)

    return ok
  }
}
