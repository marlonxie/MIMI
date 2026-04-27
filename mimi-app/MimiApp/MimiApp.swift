import SwiftUI

@main
struct MimiApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @State private var appState = AppState()

    var body: some Scene {
        MenuBarExtra("MIMI", systemImage: menuBarIcon) {
            MenuBarView(appState: appState, appDelegate: appDelegate)
        }
        Settings {
            SettingsView(appState: appState)
        }
    }

    private var menuBarIcon: String {
        guard appState.isCapturing else { return "mic" }
        return appState.isMicrophoneEnabled ? "mic.fill" : "mic.slash.fill"
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
            panel.level = .floating
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

        // 当应用内其他窗口（如 Settings）变 key 时，临时把悬浮窗降到 normal 层；
        // 对方关闭 / 失焦再回到 floating。否则 .floating(3) 会挡住 Settings(.normal=0)。
        NotificationCenter.default.addObserver(
            self, selector: #selector(otherWindowBecameKey(_:)),
            name: NSWindow.didBecomeKeyNotification, object: nil
        )
        NotificationCenter.default.addObserver(
            self, selector: #selector(otherWindowResignedKey(_:)),
            name: NSWindow.didResignKeyNotification, object: nil
        )
    }

    @objc func otherWindowBecameKey(_ notif: Notification) {
        guard let w = notif.object as? NSWindow,
              let panel = overlayPanel,
              w !== panel else { return }
        panel.level = .normal  // 让位，让 Settings 等能显示在上方
    }

    @objc func otherWindowResignedKey(_ notif: Notification) {
        guard let w = notif.object as? NSWindow,
              let panel = overlayPanel,
              w !== panel else { return }
        // 其他窗口失焦 → 恢复浮动（面试中保持字幕在面试视频上方）
        panel.level = .floating
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
    @Environment(\.openSettings) private var openSettings

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

            Button("设置…") {
                // MenuBarExtra 下 SettingsLink 偶尔只创建窗口不激活；
                // 显式 activate + openSettings 更可靠
                NSApp.activate(ignoringOtherApps: true)
                openSettings()
            }
            .keyboardShortcut(",")

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
    var currentSuggestion: ParsedSuggestion?
    var isGeneratingSuggestion: Bool = false
    var selectedSentenceId: String? = nil
    var isCapturing = false

    // 运行时两路状态（不持久 — 每次启动默认都开）
    var isMicrophoneEnabled = true
    var isSystemAudioEnabled = true

    // 持久化偏好（UserDefaults）— didSet 同时写入磁盘和推送到后端
    var interviewLanguage: String = UserDefaults.standard.string(forKey: "interviewLanguage") ?? "en" {
        didSet {
            UserDefaults.standard.set(interviewLanguage, forKey: "interviewLanguage")
            if wsClient.isConnected {
                wsClient.sendLanguages(interview: interviewLanguage, native: nativeLanguage)
            }
        }
    }
    var nativeLanguage: String = UserDefaults.standard.string(forKey: "nativeLanguage") ?? "zh" {
        didSet {
            UserDefaults.standard.set(nativeLanguage, forKey: "nativeLanguage")
            if wsClient.isConnected {
                wsClient.sendLanguages(interview: interviewLanguage, native: nativeLanguage)
            }
        }
    }
    var suggestionEnabled: Bool = (UserDefaults.standard.object(forKey: "suggestionEnabled") as? Bool) ?? false {
        didSet {
            UserDefaults.standard.set(suggestionEnabled, forKey: "suggestionEnabled")
            if wsClient.isConnected {
                wsClient.sendSuggestionEnabled(suggestionEnabled)
            }
        }
    }

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
            wsClient.sendLanguages(interview: interviewLanguage, native: nativeLanguage)
            wsClient.sendSuggestionEnabled(suggestionEnabled)
            try await audioCapture.startCapture()
            isCapturing = true
            isMicrophoneEnabled = audioCapture.isMicrophoneRunning
            isSystemAudioEnabled = audioCapture.isSystemAudioRunning
        } catch {
            print("启动捕获失败: \(error)")
        }
    }

    func stopCapture() {
        audioCapture.stopCapture()
        wsClient.sendFlush()
        isCapturing = false
    }

    /// 两步点击交互第一步：高亮某条 interviewer 字幕行，让 💡 按钮出现
    func selectSentence(_ sentenceId: String?) {
        selectedSentenceId = sentenceId
    }

    /// 两步点击第二步：对选中句触发 RAG 建议生成
    func requestSuggestion(sentenceId: String) {
        guard wsClient.isConnected else { return }
        isGeneratingSuggestion = true
        wsClient.sendManualSuggest(sentenceId: sentenceId)
        selectedSentenceId = nil
    }

    func toggleMicrophone() async {
        if isMicrophoneEnabled {
            audioCapture.stopMicrophoneCapture()
        } else {
            do {
                try await audioCapture.startMicrophoneCapture()
            } catch {
                print("麦克风启用失败: \(error)")
                return
            }
        }
        isMicrophoneEnabled = audioCapture.isMicrophoneRunning
    }

    func toggleSystemAudio() async {
        if isSystemAudioEnabled {
            audioCapture.stopSystemAudioCapture()
            isSystemAudioEnabled = false  // stop 是异步 task，立即翻转 UI 状态
        } else {
            do {
                try await audioCapture.startSystemAudioCapture()
            } catch {
                print("屏幕录制启用失败: \(error)")
                return
            }
            isSystemAudioEnabled = audioCapture.isSystemAudioRunning
        }
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
            // partial 升级 final 时 tentative 段清空（final 没有候选段）
            // 旧 server 不发新字段时 fallback：整段当 stable
            let stable = msg.stableText ?? (msg.isFinal ? msg.text : msg.text)
            let tentative = msg.isFinal ? "" : (msg.tentativeText ?? "")

            if let existing = self.translations.first(where: { $0.id == msg.sentenceId }) {
                // 已有 entry — 原地更新（partial → final，或 partial 文字变化）
                existing.original = msg.text
                existing.stableText = stable
                existing.tentativeText = tentative
                existing.isTranscriptFinal = msg.isFinal
            } else {
                // 新 entry
                let entry = TranslationEntry(
                    sentenceId: msg.sentenceId,
                    speaker: msg.speaker,
                    timestamp: msg.timestamp,
                    original: msg.text,
                    stableText: stable,
                    tentativeText: tentative,
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
            self?.currentSuggestion = ParsedSuggestion.parseOrFallback(msg.suggestion)
            self?.isGeneratingSuggestion = false
        }
    }
}
