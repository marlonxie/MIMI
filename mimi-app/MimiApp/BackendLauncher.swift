import Foundation
import AppKit

/// 启动 / 停止 PyInstaller 打包的 mimi-backend 进程。
///
/// Bundle 结构（release build）：
///     MimiApp.app/Contents/Resources/mimi-backend/mimi-backend   ← 可执行二进制
///     MimiApp.app/Contents/Resources/mimi-backend/_internal/...  ← deps
///
/// Dev 模式（Xcode Debug，无 Run Script copy）binary 不存在 → 当作"开发者手起 server.py"
/// 处理，不抛错；WSClient 重连机制会接管连接。
///
/// 进程绑定到 app 生命周期：app 退出 → AppDelegate.applicationWillTerminate → stop() →
/// SIGTERM；terminationHandler 收到非正常退出会自动重启 1 次（防 spawn loop）。
@MainActor
final class BackendLauncher {
    private var process: Process?
    private var restartCount = 0
    private let maxRestarts = 1

    /// log 文件：~/Library/Logs/MIMI/backend.log（每次启动截断；崩溃后保留可看）
    private var logURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/MIMI/backend.log")
    }

    /// 找到 bundle 内的 backend binary。dev 模式返回 nil。
    private var binaryURL: URL? {
        Bundle.main.url(
            forResource: "mimi-backend",
            withExtension: nil,
            subdirectory: "mimi-backend"
        )
    }

    func start() {
        guard let binURL = binaryURL else {
            NSLog("[backend-launcher] binary not bundled — dev mode (manual server.py)")
            return
        }
        guard process == nil else {
            NSLog("[backend-launcher] already running, skipping")
            return
        }

        let logDir = logURL.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: logDir, withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        let logHandle = try? FileHandle(forWritingTo: logURL)

        let p = Process()
        p.executableURL = binURL
        p.standardOutput = logHandle
        p.standardError = logHandle
        var env = ProcessInfo.processInfo.environment
        env["MIMI_BUNDLED"] = "1"
        p.environment = env
        p.terminationHandler = { [weak self] proc in
            Task { @MainActor [weak self] in
                self?.handleTermination(proc)
            }
        }

        do {
            try p.run()
            process = p
            NSLog("[backend-launcher] started pid=%d", p.processIdentifier)
        } catch {
            NSLog("[backend-launcher] failed to spawn: %@", String(describing: error))
        }
    }

    /// 优雅停止：SIGTERM，让 uvicorn / asyncio cleanup 跑完。terminationHandler 会清 process。
    func stop() {
        guard let p = process, p.isRunning else { return }
        // 标记主动停止：让 terminationHandler 判断 process == nil 时跳过重启
        process = nil
        p.terminate()
        let deadline = Date().addingTimeInterval(2.0)
        while p.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        if p.isRunning {
            kill(p.processIdentifier, SIGKILL)
        }
    }

    /// terminationHandler 回调：非主动 stop 导致的退出 → 自动重启 1 次。
    private func handleTermination(_ proc: Process) {
        let pid = proc.processIdentifier
        let status = proc.terminationStatus
        NSLog("[backend-launcher] exited pid=%d status=%d", pid, status)

        // process == nil 表示 stop() 已主动 reset，不重启
        guard process != nil else { return }
        process = nil

        if restartCount < maxRestarts {
            restartCount += 1
            NSLog("[backend-launcher] restart attempt %d/%d", restartCount, maxRestarts)
            start()
        } else {
            NSLog("[backend-launcher] max restarts hit, giving up — see %@", logURL.path)
        }
    }
}
