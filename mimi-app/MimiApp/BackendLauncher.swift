import Foundation
import AppKit

/// 启动 / 停止两个子进程：
///   1. ollama serve   ←  bundled in MimiApp.app/Contents/Resources/ollama-bin/
///   2. mimi-backend   ←  bundled in MimiApp.app/Contents/Resources/mimi-backend/
///
/// 顺序：先起 ollama daemon → 健康检查 listening 后 → 起 mimi-backend（mimi-backend
/// 启动时会尝试连 ollama 拉模型，要求 ollama 已 ready）。
///
/// 端口：bundled ollama 监听 11435（**不是** 默认 11434），避免和用户系统里 brew 装的
/// ollama daemon 冲突。后端 config.yaml `llm.ollama_base_url` 也指向 11435。
///
/// 隔离：模型存到 `~/Library/Application Support/MIMI/ollama-models/`（不污染 ~/.ollama）。
///
/// Dev 模式（Xcode Debug 没 Run Script copy）binary 不存在 → 当作开发者手动跑 server.py
/// 处理，不抛错；WSClient 重连机制接管。
///
/// 进程绑定到 app 生命周期：app 退出 → AppDelegate.applicationWillTerminate → stop()
/// → 顺序 SIGTERM mimi-backend 然后 ollama；terminationHandler 非主动 stop 时
/// 自动重启 1 次（防 spawn loop）。
@MainActor
final class BackendLauncher {
    // MARK: - State
    private var ollamaProcess: Process?
    private var backendProcess: Process?
    private var ollamaRestartCount = 0
    private var backendRestartCount = 0
    private let maxRestarts = 1

    /// bundled ollama 监听端口（避开默认 11434）
    static let ollamaHost = "127.0.0.1:11435"

    private var logsDir: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/MIMI", isDirectory: true)
    }
    private var ollamaLogURL: URL { logsDir.appendingPathComponent("ollama.log") }
    private var backendLogURL: URL { logsDir.appendingPathComponent("backend.log") }

    /// ollama 模型目录（卸载时清干净，不污染 ~/.ollama）
    private var ollamaModelsDir: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/MIMI/ollama-models",
                                    isDirectory: true)
    }

    private var ollamaBinaryURL: URL? {
        Bundle.main.url(
            forResource: "ollama", withExtension: nil, subdirectory: "ollama-bin"
        )
    }
    private var backendBinaryURL: URL? {
        Bundle.main.url(
            forResource: "mimi-backend", withExtension: nil, subdirectory: "mimi-backend"
        )
    }

    // MARK: - Start / Stop

    func start() {
        // 准备 log 目录
        try? FileManager.default.createDirectory(at: logsDir, withIntermediateDirectories: true)

        startOllama()
        // 等 ollama daemon 起来再起 backend（mimi-backend 启动时要拉模型，需要 daemon ready）。
        // 不卡 main thread——异步等。
        Task { @MainActor in
            let ready = await waitForOllamaReady(timeout: 30.0)
            if !ready {
                NSLog("[backend-launcher] ollama not ready after 30s — starting backend anyway")
            }
            startBackend()
        }
    }

    func stop() {
        // 顺序：先停 backend（依赖 ollama），再停 ollama
        stopBackend()
        stopOllama()
    }

    // MARK: - Ollama subprocess

    private func startOllama() {
        guard let bin = ollamaBinaryURL else {
            NSLog("[backend-launcher] ollama binary not bundled — dev mode (assume user-installed ollama on default port)")
            return
        }
        guard ollamaProcess == nil else { return }

        try? FileManager.default.createDirectory(
            at: ollamaModelsDir, withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: ollamaLogURL.path, contents: nil)
        let logHandle = try? FileHandle(forWritingTo: ollamaLogURL)

        let p = Process()
        p.executableURL = bin
        p.arguments = ["serve"]
        var env = ProcessInfo.processInfo.environment
        env["OLLAMA_HOST"] = Self.ollamaHost
        env["OLLAMA_MODELS"] = ollamaModelsDir.path
        env["OLLAMA_KEEP_ALIVE"] = "5m"
        p.environment = env
        p.standardOutput = logHandle
        p.standardError = logHandle
        p.terminationHandler = { [weak self] proc in
            Task { @MainActor [weak self] in self?.handleOllamaTermination(proc) }
        }
        do {
            try p.run()
            ollamaProcess = p
            NSLog("[backend-launcher] ollama spawned pid=%d host=%@", p.processIdentifier, Self.ollamaHost)
        } catch {
            NSLog("[backend-launcher] ollama spawn failed: %@", String(describing: error))
        }
    }

    private func stopOllama() {
        guard let p = ollamaProcess, p.isRunning else { return }
        ollamaProcess = nil
        p.terminate()
        let deadline = Date().addingTimeInterval(2.0)
        while p.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        if p.isRunning { kill(p.processIdentifier, SIGKILL) }
    }

    private func handleOllamaTermination(_ proc: Process) {
        NSLog("[backend-launcher] ollama exited status=%d", proc.terminationStatus)
        guard ollamaProcess != nil else { return }
        ollamaProcess = nil
        if ollamaRestartCount < maxRestarts {
            ollamaRestartCount += 1
            NSLog("[backend-launcher] restart ollama (%d/%d)", ollamaRestartCount, maxRestarts)
            startOllama()
        }
    }

    /// 轮询 GET /api/version，daemon ready 返回 true；超时返回 false。
    private func waitForOllamaReady(timeout: TimeInterval) async -> Bool {
        guard ollamaBinaryURL != nil else { return true }  // dev 模式不阻塞
        let deadline = Date().addingTimeInterval(timeout)
        let url = URL(string: "http://\(Self.ollamaHost)/api/version")!
        while Date() < deadline {
            do {
                var req = URLRequest(url: url)
                req.timeoutInterval = 1.0
                let (_, resp) = try await URLSession.shared.data(for: req)
                if let http = resp as? HTTPURLResponse, http.statusCode == 200 {
                    NSLog("[backend-launcher] ollama ready")
                    return true
                }
            } catch {
                // 还没起来，继续等
            }
            try? await Task.sleep(for: .milliseconds(500))
        }
        return false
    }

    // MARK: - Backend subprocess

    private func startBackend() {
        guard let bin = backendBinaryURL else {
            NSLog("[backend-launcher] mimi-backend binary not bundled — dev mode (manual server.py)")
            return
        }
        guard backendProcess == nil else { return }

        FileManager.default.createFile(atPath: backendLogURL.path, contents: nil)
        let logHandle = try? FileHandle(forWritingTo: backendLogURL)

        let p = Process()
        p.executableURL = bin
        p.standardOutput = logHandle
        p.standardError = logHandle
        var env = ProcessInfo.processInfo.environment
        env["MIMI_BUNDLED"] = "1"
        // 把 ollama host 推给 backend，让 config.yaml 之外也能覆盖
        env["MIMI_OLLAMA_BASE_URL"] = "http://\(Self.ollamaHost)"
        p.environment = env
        p.terminationHandler = { [weak self] proc in
            Task { @MainActor [weak self] in self?.handleBackendTermination(proc) }
        }
        do {
            try p.run()
            backendProcess = p
            NSLog("[backend-launcher] backend spawned pid=%d", p.processIdentifier)
        } catch {
            NSLog("[backend-launcher] backend spawn failed: %@", String(describing: error))
        }
    }

    private func stopBackend() {
        guard let p = backendProcess, p.isRunning else { return }
        backendProcess = nil
        p.terminate()
        let deadline = Date().addingTimeInterval(2.0)
        while p.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        if p.isRunning { kill(p.processIdentifier, SIGKILL) }
    }

    private func handleBackendTermination(_ proc: Process) {
        NSLog("[backend-launcher] backend exited status=%d", proc.terminationStatus)
        guard backendProcess != nil else { return }
        backendProcess = nil
        if backendRestartCount < maxRestarts {
            backendRestartCount += 1
            NSLog("[backend-launcher] restart backend (%d/%d)", backendRestartCount, maxRestarts)
            startBackend()
        }
    }
}
