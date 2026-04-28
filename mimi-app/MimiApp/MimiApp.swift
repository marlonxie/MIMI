import SwiftUI
import AppKit
import UniformTypeIdentifiers

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

// MARK: - App Delegate（管理 hub + captions + suggestion 三个浮动 panel）

@MainActor
class AppDelegate: NSObject, NSApplicationDelegate {
    var hubPanel: NSPanel?
    var captionsPanel: NSPanel?
    var suggestionPanel: NSPanel?
    weak var appState: AppState?

    /// 创建（如未创建）+ 显示三个 panel。AppState 的 captionsVisible/suggestionVisible 决定子窗是否一同打开。
    func showAllPanels(appState: AppState) {
        self.appState = appState
        appState.appDelegate = self

        if hubPanel == nil {
            hubPanel = makeFloatingPanel(
                autosaveName: "MIMI.Hub.v4",
                defaultRect: NSRect(x: 0, y: 0, width: 320, height: 40),
                rootView: AnyView(HubView(appState: appState, appDelegate: self)),
                borderless: true   // hub 自带 minus / xmark，不要系统 traffic-light
            )
        }
        if captionsPanel == nil {
            captionsPanel = makeFloatingPanel(
                autosaveName: "MIMI.Captions.v4",
                defaultRect: NSRect(x: 0, y: 0, width: 480, height: 240),
                rootView: AnyView(CaptionsView(appState: appState)),
                borderless: false
            )
        }
        if suggestionPanel == nil {
            suggestionPanel = makeFloatingPanel(
                autosaveName: "MIMI.Suggestion.v4",
                defaultRect: NSRect(x: 0, y: 0, width: 480, height: 200),
                rootView: AnyView(SuggestionView(appState: appState)),
                borderless: false
            )
        }
        applyDefaultLayoutIfNeeded()
        installNotificationsOnce()

        // hub 是 .borderless + .nonactivatingPanel，canBecomeKey 默认为 NO，
        // 用 makeKeyAndOrderFront 会触发 "called on NSPanel ... canBecomeKeyWindow=NO" 警告。
        // orderFront 即可让 hub 浮上来，鼠标点击仍然有效。
        hubPanel?.orderFront(nil)
        applyCaptionsVisibility(appState.captionsVisible)
        applySuggestionVisibility(appState.suggestionVisible)
    }

    // MARK: 显示 / 最小化 / 关闭

    func applyCaptionsVisibility(_ visible: Bool) {
        guard let panel = captionsPanel else { return }
        if visible, !panel.isVisible { panel.orderFront(nil) }
        else if !visible, panel.isVisible { panel.orderOut(nil) }
    }

    func applySuggestionVisibility(_ visible: Bool) {
        guard let panel = suggestionPanel else { return }
        if visible, !panel.isVisible { panel.orderFront(nil) }
        else if !visible, panel.isVisible { panel.orderOut(nil) }
    }

    /// 临时隐藏全部窗口（保留录音）。菜单栏"隐藏悬浮窗" + Hub minus 按钮共用。
    func minimizeAll() {
        hubPanel?.orderOut(nil)
        captionsPanel?.orderOut(nil)
        suggestionPanel?.orderOut(nil)
        // 不动 captionsVisible / suggestionVisible（临时态，不持久化）
    }

    /// 从最小化恢复。按 *Visible 状态决定子窗是否随 hub 一起出现。
    func restoreAll() {
        guard let appState else { return }
        hubPanel?.orderFront(nil)
        applyCaptionsVisibility(appState.captionsVisible)
        applySuggestionVisibility(appState.suggestionVisible)
    }

    /// 当前是否处于"全部隐藏"状态（菜单栏 toggle 文字依据此）
    var isAllHidden: Bool {
        !(hubPanel?.isVisible ?? false)
    }

    // MARK: 上传 RAG 资料

    /// NSOpenPanel 选文件 → 复制到 mimi-backend/resources/
    /// 本轮不自动触发 indexer（让用户手动 `python -m rag.indexer`）；下轮做自动
    func pickRagResources() {
        let panel = NSOpenPanel()
        panel.title = "选择简历 / 项目说明文件"
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.allowedContentTypes = [.pdf, .plainText, .text]

        guard panel.runModal() == .OK else { return }

        let resources = URL(fileURLWithPath: "/Users/marlon/MIMI/mimi-backend/resources")
        try? FileManager.default.createDirectory(at: resources, withIntermediateDirectories: true)

        var copied = 0
        for src in panel.urls {
            let dst = resources.appendingPathComponent(src.lastPathComponent)
            // 已存在则覆盖
            try? FileManager.default.removeItem(at: dst)
            do {
                try FileManager.default.copyItem(at: src, to: dst)
                copied += 1
            } catch {
                print("复制文件失败: \(src.lastPathComponent) — \(error)")
            }
        }

        let alert = NSAlert()
        alert.messageText = "已复制 \(copied) 个文件到 resources/"
        alert.informativeText = "请运行：\ncd mimi-backend && python -m rag.indexer\n重建索引后回答提示功能才会用到新资料。"
        alert.runModal()
    }

    // MARK: Panel 创建

    private func makeFloatingPanel(
        autosaveName: String,
        defaultRect: NSRect,
        rootView: AnyView,
        borderless: Bool
    ) -> NSPanel {
        let style: NSWindow.StyleMask = borderless
            ? [.borderless, .resizable, .nonactivatingPanel]
            : [.titled, .closable, .resizable, .nonactivatingPanel, .fullSizeContentView]
        let panel = NSPanel(
            contentRect: defaultRect,
            styleMask: style,
            backing: .buffered,
            defer: false
        )
        panel.level = .floating
        panel.isFloatingPanel = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isMovableByWindowBackground = true
        panel.isOpaque = false
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        // 关键：让 NSVisualEffectView 透出磨砂；不再叠 SwiftUI 实色
        panel.backgroundColor = .clear
        // 锁 dark vibrancy，无论系统外观如何，blur 都按深色 vibrancy 渲染
        panel.appearance = NSAppearance(named: .vibrantDark)

        if !borderless {
            // 保留 traffic-light（红/黄/绿），但 titlebar 透明 + .fullSizeContentView
            // 让磨砂层延伸到三圆按钮背后，得到全幅 iOS HUD 视觉
            panel.title = ""
            panel.titleVisibility = .hidden
            panel.titlebarAppearsTransparent = true
        }

        // ---- 磨砂玻璃容器（NSVisualEffectView + NSHostingView 叠层）----
        let container = NSView(frame: NSRect(origin: .zero, size: defaultRect.size))
        container.wantsLayer = true
        container.layer?.cornerRadius = Theme.Radius.panel
        container.layer?.cornerCurve  = .continuous
        container.layer?.masksToBounds = true
        container.autoresizingMask = [.width, .height]

        let blur = NSVisualEffectView(frame: container.bounds)
        blur.autoresizingMask = [.width, .height]
        blur.material = .hudWindow              // 通知中心风磨砂
        blur.blendingMode = .behindWindow
        blur.state = .active
        blur.isEmphasized = true
        container.addSubview(blur)

        // 暗色 tint 蒙板：iOS systemMaterialDark 内部也是 blur + dark tint，
        // 单独 .hudWindow 在浅色壁纸下会偏蓝偏亮，叠一层 ~0.45 alpha 黑压暗
        let tint = NSView(frame: container.bounds)
        tint.autoresizingMask = [.width, .height]
        tint.wantsLayer = true
        tint.layer?.backgroundColor = NSColor(white: 0, alpha: 0.45).cgColor
        container.addSubview(tint)

        let host = NSHostingView(rootView: rootView)
        host.frame = container.bounds
        host.autoresizingMask = [.width, .height]
        host.wantsLayer = true
        host.layer?.backgroundColor = NSColor.clear.cgColor   // 不能盖住磨砂
        container.addSubview(host)

        panel.contentView = container
        panel.setFrameAutosaveName(autosaveName)
        // 注：setFrameUsingName 会被 setFrameAutosaveName 自动调用一次
        return panel
    }

    /// 首次启动 / panel 没历史位置时，按 hub→captions→suggestion 垂直堆叠到屏幕右上
    private func applyDefaultLayoutIfNeeded() {
        guard let screen = NSScreen.main,
              let hub = hubPanel,
              let caps = captionsPanel,
              let sug = suggestionPanel else { return }

        // setFrameAutosaveName 已自动恢复历史位置；如还在 (0,0) 视为首次
        if hub.frame.origin == .zero {
            let w: CGFloat = 480
            let hubH: CGFloat = 50
            let capsH: CGFloat = 240
            let sugH: CGFloat = 200
            let gap: CGFloat = 4
            let x = screen.visibleFrame.maxX - w - 20
            var y = screen.visibleFrame.maxY - hubH - 20
            hub.setFrame(NSRect(x: x, y: y, width: w, height: hubH), display: true)
            y -= capsH + gap
            caps.setFrame(NSRect(x: x, y: y, width: w, height: capsH), display: true)
            y -= sugH + gap
            sug.setFrame(NSRect(x: x, y: y, width: w, height: sugH), display: true)
        }
    }

    // MARK: 通知

    private var notificationsInstalled = false
    private var isTerminating = false

    private func installNotificationsOnce() {
        guard !notificationsInstalled else { return }
        notificationsInstalled = true

        // 子窗 / Hub 关闭事件
        NotificationCenter.default.addObserver(
            self, selector: #selector(panelWillClose(_:)),
            name: NSWindow.willCloseNotification, object: nil
        )
        // Settings 等其他窗口出现时让位
        NotificationCenter.default.addObserver(
            self, selector: #selector(otherWindowBecameKey(_:)),
            name: NSWindow.didBecomeKeyNotification, object: nil
        )
        NotificationCenter.default.addObserver(
            self, selector: #selector(otherWindowResignedKey(_:)),
            name: NSWindow.didResignKeyNotification, object: nil
        )
    }

    @objc func panelWillClose(_ notif: Notification) {
        // 退出过程中所有 panel 都会收到 willClose；用 isTerminating 拦截，
        // 避免误把 captions/suggestion 的"被动关闭"写成 visible=false 污染偏好
        if isTerminating { return }
        guard let p = notif.object as? NSPanel else { return }
        if p === hubPanel {
            isTerminating = true
            NSApp.terminate(nil)
        } else if p === captionsPanel {
            appState?.captionsVisible = false
        } else if p === suggestionPanel {
            appState?.suggestionVisible = false
        }
    }

    @objc func otherWindowBecameKey(_ notif: Notification) {
        guard let w = notif.object as? NSWindow else { return }
        let myPanels: [NSPanel?] = [hubPanel, captionsPanel, suggestionPanel]
        if myPanels.contains(where: { $0 === w }) { return }
        myPanels.compactMap { $0 }.forEach { $0.level = .normal }
    }

    @objc func otherWindowResignedKey(_ notif: Notification) {
        guard let w = notif.object as? NSWindow else { return }
        let myPanels: [NSPanel?] = [hubPanel, captionsPanel, suggestionPanel]
        if myPanels.contains(where: { $0 === w }) { return }
        myPanels.compactMap { $0 }.forEach { $0.level = .floating }
    }
}

// MARK: - Menu Bar View

struct MenuBarView: View {
    let appState: AppState
    let appDelegate: AppDelegate
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        VStack {
            Button(appDelegate.isAllHidden ? "显示悬浮窗" : "隐藏悬浮窗") {
                if appDelegate.isAllHidden {
                    appDelegate.showAllPanels(appState: appState)
                } else {
                    appDelegate.minimizeAll()
                }
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

    // === Hub 子窗可见性（持久化 + 联动 AppDelegate）===
    var captionsVisible: Bool = (UserDefaults.standard.object(forKey: "captionsVisible") as? Bool) ?? true {
        didSet {
            UserDefaults.standard.set(captionsVisible, forKey: "captionsVisible")
            appDelegate?.applyCaptionsVisibility(captionsVisible)
        }
    }
    var suggestionVisible: Bool = (UserDefaults.standard.object(forKey: "suggestionVisible") as? Bool) ?? true {
        didSet {
            UserDefaults.standard.set(suggestionVisible, forKey: "suggestionVisible")
            appDelegate?.applySuggestionVisibility(suggestionVisible)
        }
    }

    // === API key / LLM provider ===
    var llmProvider: String = UserDefaults.standard.string(forKey: "llmProvider") ?? "gemini" {
        didSet { UserDefaults.standard.set(llmProvider, forKey: "llmProvider") }
    }
    var apiKey: String = ""
    var translationReady: Bool = false
    var ragReady: Bool = false
    var ragLoaded: Bool = false

    let wsClient = WebSocketClient()
    let audioCapture = AudioCaptureManager()
    weak var appDelegate: AppDelegate?

    init() {
        setupCallbacks()
    }

    func startCapture() async {
        wsClient.connect()
        do {
            try await audioCapture.startCapture()
            isCapturing = true
            isMicrophoneEnabled = audioCapture.isMicrophoneRunning
            isSystemAudioEnabled = audioCapture.isSystemAudioRunning
        } catch {
            print("启动捕获失败: \(error)")
        }
    }

    /// 用户在 Settings 主动按"保存并应用"时调（强制推送，可覆盖 .env）
    func applyApiKey() {
        guard !apiKey.isEmpty else { return }
        _ = Keychain.save(key: llmProvider, value: apiKey)
        if wsClient.isConnected {
            wsClient.sendApiKeys(provider: llmProvider, apiKey: apiKey)
        }
    }

    /// SettingsView 切 provider 时调，自动从 Keychain 读对应 key 填到 UI
    func loadApiKeyForCurrentProvider() {
        apiKey = Keychain.load(key: llmProvider) ?? ""
    }

    func stopCapture() {
        audioCapture.stopCapture()
        wsClient.sendFlush()
        isCapturing = false
    }

    func selectSentence(_ sentenceId: String?) {
        selectedSentenceId = sentenceId
    }

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
            if !wsClient.isConnected { wsClient.connect() }
            do {
                try await audioCapture.startMicrophoneCapture()
            } catch {
                print("麦克风启用失败: \(error)")
                return
            }
        }
        isMicrophoneEnabled = audioCapture.isMicrophoneRunning
        isCapturing = isMicrophoneEnabled || isSystemAudioEnabled
    }

    func toggleSystemAudio() async {
        if isSystemAudioEnabled {
            audioCapture.stopSystemAudioCapture()
            isSystemAudioEnabled = false
        } else {
            if !wsClient.isConnected { wsClient.connect() }
            do {
                try await audioCapture.startSystemAudioCapture()
            } catch {
                print("屏幕录制启用失败: \(error)")
                return
            }
            isSystemAudioEnabled = audioCapture.isSystemAudioRunning
        }
        isCapturing = isMicrophoneEnabled || isSystemAudioEnabled
    }

    func cleanup() {
        audioCapture.stopCapture()
        wsClient.disconnect()
    }

    private func setupCallbacks() {
        audioCapture.onAudioChunk = { [weak self] data, source in
            self?.wsClient.sendAudio(data, source: source)
        }

        wsClient.onTranscript = { [weak self] msg in
            guard let self else { return }
            let stable = msg.stableText ?? msg.text
            let tentative = msg.isFinal ? "" : (msg.tentativeText ?? "")

            if let existing = self.translations.first(where: { $0.id == msg.sentenceId }) {
                existing.original = msg.text
                existing.stableText = stable
                existing.tentativeText = tentative
                existing.isTranscriptFinal = msg.isFinal
            } else {
                let entry = TranslationEntry(
                    sentenceId: msg.sentenceId,
                    speaker: msg.speaker,
                    timestamp: msg.timestamp,
                    original: msg.text,
                    stableText: stable,
                    tentativeText: tentative,
                    isTranscriptFinal: msg.isFinal
                )
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
        }

        wsClient.onTranslationFinal = { [weak self] msg in
            guard let self else { return }
            if let entry = self.translations.first(where: { $0.id == msg.sentenceId }) {
                entry.translation = msg.text
                entry.isTranslationComplete = true
            }
        }

        wsClient.onSuggestion = { [weak self] msg in
            self?.currentSuggestion = ParsedSuggestion.parseOrFallback(msg.suggestion)
            self?.isGeneratingSuggestion = false
        }

        wsClient.onStatus = { [weak self] msg in
            guard let self else { return }
            self.translationReady = msg.translatorReady
            self.ragReady = msg.ragReady
            self.ragLoaded = msg.ragLoaded
            // 智能分流：仅在后端 not_ready && Keychain 有 key 时被动推送
            if !msg.translatorReady, let stored = Keychain.load(key: self.llmProvider) {
                self.apiKey = stored
                self.wsClient.sendApiKeys(provider: self.llmProvider, apiKey: stored)
            }
        }

        wsClient.onApiKeysAck = { [weak self] msg in
            guard let self else { return }
            self.translationReady = msg.translatorReady
            self.ragReady = msg.ragReady
        }

        // 连接建立后才能可靠发消息（sendJSON 有 isConnected 守卫）
        wsClient.onConnect = { [weak self] in
            guard let self else { return }
            self.wsClient.sendConfig(source: "interviewer")
            self.wsClient.sendLanguages(interview: self.interviewLanguage,
                                         native: self.nativeLanguage)
            self.wsClient.sendSuggestionEnabled(self.suggestionEnabled)
            self.wsClient.sendQueryStatus()
        }
    }
}
