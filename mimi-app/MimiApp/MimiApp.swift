import SwiftUI

@main
struct MimiApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @State private var appState = AppState()

    var body: some Scene {
        MenuBarExtra("MIMI", systemImage: appState.isCapturing ? "mic.fill" : "mic") {
            MenuBarView(appState: appState, appDelegate: appDelegate)
        }
    }
}

// MARK: - App Delegate (管理悬浮窗)

@MainActor
class AppDelegate: NSObject, NSApplicationDelegate {
    var overlayPanel: NSPanel?
    var appState: AppState?

    func showOverlay(appState: AppState) {
        self.appState = appState

        if let panel = overlayPanel {
            panel.makeKeyAndOrderFront(nil)
            return
        }

        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 500, height: 450),
            styleMask: [.titled, .closable, .resizable, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.title = "MIMI 面试助手"
        panel.level = .floating
        panel.isFloatingPanel = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isMovableByWindowBackground = true
        panel.backgroundColor = NSColor(white: 0, alpha: 0.85)
        panel.isOpaque = false
        panel.titlebarAppearsTransparent = true
        panel.titleVisibility = .hidden

        if let screen = NSScreen.main {
            let x = screen.frame.width - 520
            let y = screen.frame.height - 500
            panel.setFrameOrigin(NSPoint(x: x, y: y))
        }

        // 只创建一次 — @Observable appState 自动驱动 SwiftUI 更新
        let hostingView = NSHostingView(
            rootView: OverlayWindowContent(appState: appState)
        )
        panel.contentView = hostingView
        panel.makeKeyAndOrderFront(nil)
        overlayPanel = panel
    }

    func hideOverlay() {
        overlayPanel?.close()
        overlayPanel = nil
    }
}

// MARK: - Menu Bar View

struct MenuBarView: View {
    let appState: AppState
    let appDelegate: AppDelegate

    var body: some View {
        VStack {
            Button("打开悬浮窗") {
                appDelegate.showOverlay(appState: appState)
            }

            Divider()

            if appState.isCapturing {
                Button("停止录音") {
                    appState.stopCapture()
                }
            } else {
                Button("开始录音") {
                    Task { await appState.startCapture() }
                }
            }

            Divider()

            HStack {
                Circle()
                    .fill(appState.wsClient.isConnected ? Color.green : Color.red)
                    .frame(width: 8, height: 8)
                Text(appState.wsClient.isConnected ? "后端已连接" : "后端未连接")
            }

            Divider()

            Button("导出对话记录") {
                appState.wsClient.sendExport()
            }

            Button("退出") {
                appState.cleanup()
                NSApplication.shared.terminate(nil)
            }
            .keyboardShortcut("q")
        }
        .padding(4)
    }
}

// MARK: - App State

@MainActor
@Observable
class AppState {
    var translations: [TranslationEntry] = []
    var currentSuggestion: String?
    var isCapturing = false

    let wsClient = WebSocketClient()
    let audioCapture = AudioCaptureManager()

    init() {
        setupCallbacks()
        // 不在 init 时自动连接，等用户点开始录音
    }

    func startCapture() async {
        wsClient.connect()
        do {
            wsClient.sendConfig(source: "interviewer")
            try await audioCapture.startCapture()
            isCapturing = true
        } catch {
            print("启动捕获失败: \(error)")
        }
    }

    func stopCapture() {
        audioCapture.stopCapture()
        wsClient.sendFlush()
        isCapturing = false
    }

    func cleanup() {
        audioCapture.stopCapture()
        wsClient.disconnect()
    }

    private func setupCallbacks() {
        audioCapture.onAudioChunk = { [weak self] data, source in
            // source 嵌入音频消息本身（前缀字节），不再用 sendConfig 切换
            self?.wsClient.sendAudio(data, source: source)
        }

        wsClient.onTranscript = { [weak self] msg in
            guard let self else { return }
            if let existing = self.translations.first(where: { $0.id == msg.sentenceId }) {
                // 已有 entry — 原地更新（partial → final，或 partial 文字变化）
                existing.original = msg.text
                existing.isTranscriptFinal = msg.isFinal
            } else {
                // 新 entry
                let entry = TranslationEntry(
                    sentenceId: msg.sentenceId,
                    speaker: msg.speaker,
                    timestamp: msg.timestamp,
                    original: msg.text,
                    isTranscriptFinal: msg.isFinal
                )
                // insert_after: 多句拆分时，插入到指定 ID 后面（保持阅读顺序）
                if let afterId = msg.insertAfter,
                   let idx = self.translations.firstIndex(where: { $0.id == afterId }) {
                    self.translations.insert(entry, at: idx + 1)
                } else {
                    self.translations.append(entry)
                }
            }
        }

        wsClient.onTranslationDelta = { [weak self] msg in
            guard let self else { return }
            if let entry = self.translations.first(where: { $0.id == msg.sentenceId }) {
                entry.translation += msg.delta
            }
            // 找不到就丢弃 — 正常情况下 transcript 总是先到
        }

        wsClient.onTranslationFinal = { [weak self] msg in
            guard let self else { return }
            if let entry = self.translations.first(where: { $0.id == msg.sentenceId }) {
                entry.translation = msg.text  // 用完整文本覆盖，避免 delta 拼接误差
                entry.isTranslationComplete = true
            }
        }

        wsClient.onSuggestion = { [weak self] msg in
            self?.currentSuggestion = msg.suggestion
        }
    }
}
