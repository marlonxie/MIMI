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
    var onboardingPanel: NSPanel?
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

        // 启动预热：让 audio engine 跑、WS 连。1-3s VP 启用成本付在加载阶段，
        // 之后用户 toggle 都瞬时（mic engine 保活；speaker 重启 ~0.5s）。
        // 失败时 toggle 内 try/catch 把 isXEnabled 维持 false，hub 显示 OFF 可重试。
        Task { @MainActor in
            await appState.toggleMicrophone()
            await appState.toggleSystemAudio()
        }

        // 首次启动弹教程
        if !appState.hasCompletedOnboarding {
            showOnboarding(appState: appState)
        }
    }

    /// 弹出 OnboardingPanel。Settings 的"重看教程"按钮也调它。
    func showOnboarding(appState: AppState) {
        // 已存在则直接 front
        if let panel = onboardingPanel {
            panel.orderFrontRegardless()
            return
        }
        let panel = makeFloatingPanel(
            autosaveName: "MIMI.Onboarding.v1",
            defaultRect: NSRect(x: 0, y: 0, width: 520, height: 380),
            rootView: AnyView(OnboardingView(appState: appState, onClose: { [weak self] in
                self?.onboardingPanel?.close()
                self?.onboardingPanel = nil
            })),
            borderless: false
        )
        onboardingPanel = panel
        panel.center()
        panel.orderFrontRegardless()
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
        let lang = appState?.uiLang ?? .zh
        let panel = NSOpenPanel()
        panel.title = L.t("upload.title", lang: lang)
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
        alert.messageText = String(format: L.t("upload.alert.message", lang: lang), copied)
        alert.informativeText = L.t("upload.alert.info", lang: lang)
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
            Button(appDelegate.isAllHidden ? appState.t("menu.show") : appState.t("menu.hide")) {
                if appDelegate.isAllHidden {
                    appDelegate.showAllPanels(appState: appState)
                } else {
                    appDelegate.minimizeAll()
                }
            }

            Divider()

            HStack {
                Circle()
                    .fill(appState.wsClient.isConnected ? Color.green : Color.red)
                    .frame(width: 8, height: 8)
                Text(appState.wsClient.isConnected
                    ? appState.t("menu.connected")
                    : appState.t("menu.disconnected"))
            }

            Divider()

            Button(appState.t("menu.export")) {
                appState.wsClient.sendExport()
            }

            Button(appState.t("menu.settings")) {
                NSApp.activate(ignoringOtherApps: true)
                openSettings()
            }
            .keyboardShortcut(",")

            Button(appState.t("menu.quit")) {
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

    /// 录音单一来源真相：mic 或 speaker 任一在跑就视为录音中
    var isCapturing: Bool {
        isMicrophoneEnabled || isSystemAudioEnabled
    }

    // 运行时两路状态（不持久）。默认 false：启动后由 AppDelegate 预热阶段调
    // toggleMicrophone / toggleSystemAudio 把它们置 true，避免"视觉 ↔ 实际不一致"
    var isMicrophoneEnabled = false
    var isSystemAudioEnabled = false

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

    // === Onboarding（首次启动教程）===
    var hasCompletedOnboarding: Bool = UserDefaults.standard.bool(forKey: "hasCompletedOnboarding") {
        didSet { UserDefaults.standard.set(hasCompletedOnboarding, forKey: "hasCompletedOnboarding") }
    }
    /// 当前 onboarding 步骤 (0..5)。Step 0 = 等 backend；Step 1-4 = 教程；Step 5 = 完成屏
    var onboardingStep: Int = 0
    /// backend 是否已就绪（WS 已连）。OnboardingView Step 0 用它决定显示 spinner 还是 "下一步"
    var backendReady: Bool { wsClient.isConnected }

    // === 界面语言（UI i18n）===
    var uiLanguage: String = UserDefaults.standard.string(forKey: "uiLanguage") ?? "zh" {
        didSet { UserDefaults.standard.set(uiLanguage, forKey: "uiLanguage") }
    }
    /// 解析后的 UILang，给查找用
    var uiLang: UILang { UILang(rawValue: uiLanguage) ?? .zh }
    /// 翻译查找快捷方法。视图调 `appState.t("key")`，依赖 uiLanguage 自动追踪重渲染
    func t(_ key: String) -> String { L.t(key, lang: uiLang) }

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
        flushIfBothOff()
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
        flushIfBothOff()
    }

    /// 两路都关时让后端把 pending 的最后半句强制提交（避免"半句飘着"）。
    /// 替代之前 `stopCapture()` 路径里手动 `sendFlush`，让 hub toggle 和（已删的）
    /// 菜单 stop 走同一条收尾路径。
    private func flushIfBothOff() {
        if !isMicrophoneEnabled && !isSystemAudioEnabled && wsClient.isConnected {
            wsClient.sendFlush()
        }
    }

    func cleanup() {
        audioCapture.stopMicrophoneCapture()
        audioCapture.stopSystemAudioCapture()
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
