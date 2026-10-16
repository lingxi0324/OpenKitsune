// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "OpenkitsuneNativeAuth",
    platforms: [.iOS(.v15)],
    // Must match Capacitor's generated product name for @openkitsune/native-auth.
    products: [.library(name: "OpenkitsuneNativeAuth", targets: ["NativeAuthPlugin"])],
    dependencies: [.package(url: "https://github.com/ionic-team/capacitor-swift-pm.git", from: "8.0.0")],
    targets: [.target(name: "NativeAuthPlugin", dependencies: [
        .product(name: "Capacitor", package: "capacitor-swift-pm"),
        .product(name: "Cordova", package: "capacitor-swift-pm")
    ], path: "ios/Sources/NativeAuthPlugin")]
)
