// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "MimiApp",
    platforms: [
        .macOS(.v15)
    ],
    targets: [
        .executableTarget(
            name: "MimiApp",
            path: "MimiApp"
        )
    ]
)
