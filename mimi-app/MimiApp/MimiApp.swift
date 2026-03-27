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
            contentRect: NSRect(x: 0, y: 0, width: 500, height: 400),
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

        // 居中偏右上
        if let screen = NSScreen.main {
            let x = screen.frame.width - 520
            let y = screen.frame.height - 450
            panel.setFrameOrigin(NSPoint(x: x, y: y))
        }

        let hostingView = NSHostingView(
            rootView: OverlayWindowContent(
                translations: appState.translations,
                suggestion: appState.currentSuggestion
            )
        )
        panel.contentView = hostingView
        panel.makeKeyAndOrderFront(nil)
        overlayPanel = panel

        // 监听 appState 变化，更新窗口内容
        startUpdating(appState: appState)
    }

    func hideOverlay() {
        overlayPanel?.close()
        overlayPanel = nil
    }

    private func startUpdating(appState: AppState) {
        Task { @MainActor in
            while overlayPanel != nil {
                try? await Task.sleep(for: .milliseconds(300))
                guard let panel = overlayPanel, let state = self.appState else { break }
                let hostingView = NSHostingView(
                    rootView: OverlayWindowContent(
                        translations: state.translations,
                        suggestion: state.currentSuggestion
                    )
                )
                panel.contentView = hostingView
            }
        }
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
            self?.wsClient.sendConfig(source: source)
            self?.wsClient.sendAudio(data)
        }

        wsClient.onTranslation = { [weak self] msg in
            let entry = TranslationEntry(
                speaker: msg.speaker,
                original: msg.original,
                translation: msg.translation,
                timestamp: msg.timestamp
            )
            self?.translations.append(entry)
        }

        wsClient.onSuggestion = { [weak self] msg in
            self?.currentSuggestion = msg.suggestion
        }
    }
}
