import SwiftUI

/// 首次启动教程。6 步骤（0..5）：
/// - Step 0：欢迎 + 等 backend ready（spinner / "下一步"）
/// - Step 1-4：教程（Hub / Captions / Suggestion / Settings）
/// - Step 5：完成屏
///
/// 用 NSPanel 居中浮在桌面上（由 AppDelegate.showOnboarding 创建）。
/// 关闭路径：用户点"完成"调 onClose；写 `hasCompletedOnboarding=true`。
struct OnboardingView: View {
    @Bindable var appState: AppState
    let onClose: () -> Void

    private let totalSteps = 6   // 0..5

    var body: some View {
        VStack(spacing: 0) {
            // === 顶部：标题 + 进度点 ===
            VStack(spacing: 6) {
                Text(stepTitle)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundColor(Theme.labelPrimary)
                progressDots
            }
            .padding(.top, 24)
            .padding(.bottom, 16)

            Divider().background(Theme.separator)

            // === 中部：当前 step 内容 ===
            ScrollView {
                stepBody
                    .padding(.horizontal, 24)
                    .padding(.vertical, 20)
            }
            .frame(maxHeight: .infinity)

            Divider().background(Theme.separator)

            // === 底部：导航按钮 ===
            HStack(spacing: 12) {
                if appState.onboardingStep > 0 && appState.onboardingStep < totalSteps - 1 {
                    Button(appState.t("onboarding.back")) {
                        appState.onboardingStep -= 1
                    }
                    .buttonStyle(.plain)
                    .foregroundColor(Theme.labelSecondary)
                }

                Spacer()

                if appState.onboardingStep < totalSteps - 1 {
                    Button(appState.t("onboarding.skip")) {
                        finish()
                    }
                    .buttonStyle(.plain)
                    .foregroundColor(Theme.labelTertiary)
                }

                primaryButton
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 16)
        }
        .frame(width: 520, height: 380)
    }

    // MARK: - Header

    private var stepTitle: String {
        switch appState.onboardingStep {
        case 0: return appState.t("onboarding.welcome.title")
        case 1: return appState.t("onboarding.hub.title")
        case 2: return appState.t("onboarding.captions.title")
        case 3: return appState.t("onboarding.suggestion.title")
        case 4: return appState.t("onboarding.settings.title")
        case 5: return appState.t("onboarding.done.title")
        default: return ""
        }
    }

    private var progressDots: some View {
        HStack(spacing: 6) {
            ForEach(0..<totalSteps, id: \.self) { i in
                Circle()
                    .fill(i == appState.onboardingStep ? Theme.systemBlue : Theme.labelQuaternary)
                    .frame(width: 6, height: 6)
            }
        }
    }

    // MARK: - Body per step

    @ViewBuilder
    private var stepBody: some View {
        switch appState.onboardingStep {
        case 0: welcomeBody
        case 1: hubBody
        case 2: captionsBody
        case 3: suggestionBody
        case 4: settingsBody
        case 5: doneBody
        default: EmptyView()
        }
    }

    // Step 0
    private var welcomeBody: some View {
        VStack(alignment: .center, spacing: 16) {
            Image(systemName: "waveform.circle.fill")
                .font(.system(size: 56, weight: .light))
                .foregroundStyle(Theme.systemBlue)
            Text(appState.t("onboarding.welcome.subtitle"))
                .font(Theme.bodyFont)
                .foregroundColor(Theme.labelSecondary)
                .multilineTextAlignment(.center)

            Spacer().frame(height: 8)

            // 状态优先级：
            // 1. 有模型在下载 → 显示进度条（占大头：首启 Qwen3 2.6GB / Whisper 500MB）
            // 2. backend WS 已连 → 绿勾 "准备完成"
            // 3. 等连接 → 旋转 spinner
            if !modelsInProgress.isEmpty {
                modelProgressView
            } else if appState.backendReady {
                HStack(spacing: 8) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(Theme.systemGreen)
                    Text(appState.t("onboarding.welcome.ready"))
                        .foregroundColor(Theme.labelPrimary)
                }
                .font(Theme.bodyFont)
            } else {
                VStack(spacing: 8) {
                    HStack(spacing: 8) {
                        ProgressView().scaleEffect(0.6).frame(width: 14, height: 14)
                        Text(appState.t("onboarding.welcome.preparing"))
                            .foregroundColor(Theme.labelPrimary)
                    }
                    .font(Theme.bodyFont)
                    Text(appState.t("onboarding.welcome.preparingHint"))
                        .font(.caption2)
                        .foregroundColor(Theme.labelTertiary)
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    /// 还在下载的模型（completed < total）
    private var modelsInProgress: [(String, AppState.ModelProgress)] {
        appState.modelProgress
            .filter { !$0.value.isReady }
            .sorted { $0.key < $1.key }
            .map { ($0.key, $0.value) }
    }

    private var modelProgressView: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(modelsInProgress, id: \.0) { (name, p) in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text(displayName(forModel: name))
                            .font(Theme.bodyFont)
                            .foregroundColor(Theme.labelPrimary)
                        Spacer()
                        Text("\(formatBytes(p.completed)) / \(formatBytes(p.total))")
                            .font(.caption2)
                            .foregroundColor(Theme.labelSecondary)
                    }
                    ProgressView(value: Double(p.completed), total: Double(max(p.total, 1)))
                    if !p.status.isEmpty {
                        Text(p.status)
                            .font(.caption2)
                            .foregroundColor(Theme.labelTertiary)
                    }
                }
            }
        }
        .padding(.horizontal, 20)
    }

    private func displayName(forModel name: String) -> String {
        switch name {
        case "qwen3": return "Qwen3 (本地 LLM)"
        case "whisper": return "Whisper (语音识别)"
        default: return name
        }
    }

    private func formatBytes(_ bytes: Int64) -> String {
        let mb = Double(bytes) / 1024 / 1024
        if mb < 1024 { return String(format: "%.0f MB", mb) }
        return String(format: "%.2f GB", mb / 1024)
    }

    // Step 1: Hub 8 个按钮
    private var hubBody: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(appState.t("onboarding.hub.intro"))
                .font(Theme.bodyFont)
                .foregroundColor(Theme.labelSecondary)
                .padding(.bottom, 4)

            hubRow("xmark", color: Theme.systemRed, key: "onboarding.hub.close")
            hubRow("minus", color: Theme.labelSecondary, key: "onboarding.hub.minimize")
            hubRow("mic.fill", color: Theme.systemBlue, key: "onboarding.hub.mic")
            hubRow("speaker.wave.2.fill", color: Theme.systemBlue, key: "onboarding.hub.speaker")
            hubRow("translate", color: Theme.systemBlue, key: "onboarding.hub.cap")
            hubRow("sparkles", color: Theme.systemBlue, key: "onboarding.hub.sug")
            hubRow("square.and.arrow.up", color: Theme.systemBlue, key: "onboarding.hub.upload")
            hubRow("gearshape.fill", color: Theme.systemBlue, key: "onboarding.hub.settings")
        }
    }

    private func hubRow(_ icon: String, color: Color, key: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 13, weight: .regular))
                .foregroundStyle(color)
                .frame(width: 22, height: 18)
            Text(appState.t(key))
                .font(Theme.bodyFont)
                .foregroundColor(Theme.labelPrimary)
        }
    }

    // Step 2: Captions
    private var captionsBody: some View {
        VStack(alignment: .leading, spacing: 12) {
            captionRow("person.2.fill", color: Theme.systemBlue, key: "onboarding.captions.speaker")
            captionRow("text.alignleft", color: Theme.labelSecondary, key: "onboarding.captions.text")
            captionRow("lightbulb.fill", color: Theme.warningAccent, key: "onboarding.captions.click")
        }
    }

    private func captionRow(_ icon: String, color: Color, key: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 16, weight: .regular))
                .foregroundStyle(color)
                .frame(width: 24, height: 22)
            Text(appState.t(key))
                .font(Theme.bodyFont)
                .foregroundColor(Theme.labelPrimary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    // Step 3: Suggestion
    private var suggestionBody: some View {
        VStack(alignment: .leading, spacing: 14) {
            captionRow("brain", color: Theme.labelPrimary, key: "onboarding.suggestion.understanding")
            captionRow("list.bullet", color: Theme.systemOrange, key: "onboarding.suggestion.keyPoints")
            captionRow("text.bubble.fill", color: Theme.labelSecondary, key: "onboarding.suggestion.sample")
            Divider().background(Theme.separator).padding(.vertical, 4)
            HStack(spacing: 8) {
                Image(systemName: "info.circle")
                    .foregroundStyle(Theme.warningAccent)
                Text(appState.t("onboarding.suggestion.note"))
                    .font(.caption)
                    .foregroundColor(Theme.labelSecondary)
            }
        }
    }

    // Step 4: Settings
    private var settingsBody: some View {
        VStack(alignment: .leading, spacing: 12) {
            captionRow("globe", color: Theme.systemBlue, key: "onboarding.settings.lang")
            captionRow("paintbrush", color: Theme.systemBlue, key: "onboarding.settings.ui")
            captionRow("lightbulb", color: Theme.systemBlue, key: "onboarding.settings.sug")
            captionRow("key", color: Theme.systemBlue, key: "onboarding.settings.api")
        }
    }

    // Step 5: 完成
    private var doneBody: some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 48, weight: .light))
                .foregroundStyle(Theme.systemGreen)
            Text(appState.t("onboarding.done.body"))
                .font(Theme.bodyFont)
                .foregroundColor(Theme.labelSecondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Primary action button

    private var primaryButton: some View {
        Button(primaryButtonLabel) {
            primaryButtonAction()
        }
        .buttonStyle(.borderedProminent)
        .tint(Theme.systemBlue)
        .disabled(primaryButtonDisabled)
    }

    private var primaryButtonLabel: String {
        appState.onboardingStep == totalSteps - 1
            ? appState.t("onboarding.done")
            : appState.t("onboarding.next")
    }

    /// Step 0 时 backend 没就绪 → 禁用"下一步"
    private var primaryButtonDisabled: Bool {
        appState.onboardingStep == 0 && !appState.backendReady
    }

    private func primaryButtonAction() {
        if appState.onboardingStep == totalSteps - 1 {
            finish()
        } else {
            appState.onboardingStep += 1
        }
    }

    private func finish() {
        appState.hasCompletedOnboarding = true
        appState.onboardingStep = 0   // 重置，方便重看
        onClose()
    }
}

// MARK: - Previews

#Preview("step 0 - waiting") {
    let s: AppState = {
        let s = AppState()
        s.onboardingStep = 0
        return s
    }()
    ZStack {
        Theme.panelBaseSolid
        OnboardingView(appState: s, onClose: {})
    }
    .frame(width: 520, height: 380)
}

#Preview("step 1 - hub") {
    let s: AppState = {
        let s = AppState()
        s.onboardingStep = 1
        return s
    }()
    ZStack {
        Theme.panelBaseSolid
        OnboardingView(appState: s, onClose: {})
    }
    .frame(width: 520, height: 380)
}

#Preview("step 5 - done") {
    let s: AppState = {
        let s = AppState()
        s.onboardingStep = 5
        return s
    }()
    ZStack {
        Theme.panelBaseSolid
        OnboardingView(appState: s, onClose: {})
    }
    .frame(width: 520, height: 380)
}
