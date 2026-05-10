import SwiftUI
import AppKit

struct SettingsView: View {
    @Bindable var appState: AppState

    var body: some View {
        TabView {
            languageTab
                .tabItem { Label(appState.t("settings.tab.language"), systemImage: "globe") }
                .padding()

            uiTab
                .tabItem { Label(appState.t("settings.tab.ui"), systemImage: "paintbrush") }
                .padding()

            suggestionTab
                .tabItem { Label(appState.t("settings.tab.suggestion"), systemImage: "lightbulb") }
                .padding()

            ResourcesTab(appState: appState)
                .tabItem { Label(appState.t("settings.tab.resources"), systemImage: "doc.on.doc") }
                .padding()

            apiKeyTab
                .tabItem { Label(appState.t("settings.tab.api"), systemImage: "key") }
                .padding()
        }
        .frame(width: 480, height: 380)
    }

    // MARK: - Language tab

    private var languageTab: some View {
        Form {
            Picker(appState.t("settings.interviewLanguage"),
                   selection: $appState.interviewLanguage) {
                Text("English").tag("en")
                Text("Deutsch").tag("de")
            }
            Picker(appState.t("settings.nativeLanguage"),
                   selection: $appState.nativeLanguage) {
                Text("中文").tag("zh")
                Text("English").tag("en")
            }
            Text(appState.t("settings.languageHint"))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - UI (interface language) tab

    private var uiTab: some View {
        Form {
            Picker(appState.t("settings.uiLanguage"), selection: $appState.uiLanguage) {
                ForEach(UILang.allCases, id: \.rawValue) { lang in
                    Text(lang.displayName).tag(lang.rawValue)
                }
            }
            Text(appState.t("settings.uiLanguage.hint"))
                .font(.caption)
                .foregroundStyle(.secondary)

            Divider().padding(.vertical, 6)

            Button(appState.t("settings.replayOnboarding")) {
                appState.hasCompletedOnboarding = false
                appState.onboardingStep = 0
                appState.appDelegate?.showOnboarding(appState: appState)
            }
        }
    }

    // MARK: - Suggestion tab

    private var suggestionTab: some View {
        Form {
            Toggle(appState.t("settings.suggestion.toggle"),
                   isOn: $appState.suggestionEnabled)
            Text(appState.t("settings.suggestion.hint"))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - API Key tab

    private var apiKeyTab: some View {
        Form {
            Picker(appState.t("settings.api.provider"), selection: $appState.llmProvider) {
                Text("Google Gemini").tag("gemini")
                Text("Anthropic Claude").tag("claude")
                Text(appState.t("settings.api.local")).tag("ollama")
            }
            .onChange(of: appState.llmProvider) { _, _ in
                appState.loadApiKeyForCurrentProvider()
                // 切到任何 provider 都自动尝试 apply：
                // - 本地 provider：总是成功（无需 key）
                // - 远程 provider：apiKey 非空就更新 + 切；空但 backend 已加载过 key
                //   （.env / Keychain 之前存）也成功；都没有 backend 才拒绝。
                // 这样切回曾经用过的 cloud provider 不需要重新粘 key。
                appState.applyApiKey()
            }

            // picker 与 backend 实际 active_provider 不一致时的橙色提示。
            // 触发场景：用户改了 picker 但还没 apply；或后端启动时缺 key 走 ollama fallback
            // 但前端 UserDefaults 仍记得上次选的 gemini。
            if !appState.activeProvider.isEmpty
               && appState.activeProvider != appState.llmProvider {
                HStack(alignment: .top, spacing: 6) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(String(format: appState.t("settings.api.activeProvider"),
                                    providerDisplayName(appState.activeProvider)))
                            .font(.caption)
                        Text(appState.t("settings.api.providerMismatch"))
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            if appState.llmProvider == "ollama" {
                HStack(alignment: .top, spacing: 6) {
                    Image(systemName: "checkmark.shield").foregroundStyle(.green)
                    Text(appState.t("settings.api.localHint"))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Button(appState.t("settings.api.save")) {
                    appState.applyApiKey()
                }
            } else {
                SecureField("API Key",
                            text: $appState.apiKey,
                            prompt: Text(appState.t("settings.api.placeholder")))
                    .textFieldStyle(.roundedBorder)

                HStack {
                    Button(appState.t("settings.api.save")) {
                        appState.applyApiKey()
                    }
                    .disabled(appState.apiKey.isEmpty)

                    Spacer()

                    if appState.translationReady {
                        Label(appState.t("settings.api.translationReady"),
                              systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                            .font(.caption)
                    }
                }

                // ".env 已配置就绪" 只在 picker 与 backend 一致时显示 — 否则会误导
                // （比如 backend 是 ollama fallback，picker 是 gemini 空 key，旧逻辑会
                // 错误地说"gemini .env 已就绪"）。不一致的情况由上方 mismatch 提示处理。
                if appState.translationReady
                   && appState.apiKey.isEmpty
                   && appState.activeProvider == appState.llmProvider {
                    HStack(alignment: .top, spacing: 6) {
                        Image(systemName: "info.circle").foregroundStyle(.blue)
                        Text(appState.t("settings.api.envHint"))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Text(appState.t("settings.api.keychainHint"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    /// 把 backend 返回的裸 provider id 转成本地化的显示名（供 mismatch 提示用）。
    /// 未知 provider 直接返回 id，至少不会丢信息。
    private func providerDisplayName(_ provider: String) -> String {
        let key = "settings.api.providerName.\(provider)"
        let resolved = appState.t(key)
        return resolved == key ? provider : resolved
    }
}

// MARK: - Resources tab

/// 已上传参考资料管理：列出 + 单文件删除 + 一键清除。
/// 数据来自 AppState.resources（由 wsClient.onResourcesList 推送填充）。
private struct ResourcesTab: View {
    @Bindable var appState: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Button {
                    appState.appDelegate?.pickRagResources()
                } label: {
                    Label(appState.t("resources.uploadButton"), systemImage: "square.and.arrow.up")
                }
                Spacer()
            }

            if appState.resources.isEmpty {
                VStack {
                    Spacer()
                    Text(appState.t("resources.empty"))
                        .foregroundStyle(.secondary)
                        .font(.callout)
                    Spacer()
                }
                .frame(maxWidth: .infinity, minHeight: 140)
            } else {
                ScrollView {
                    VStack(spacing: 0) {
                        ForEach(appState.resources) { file in
                            ResourceRow(file: file, appState: appState)
                            Divider()
                        }
                    }
                }
                .frame(maxHeight: 220)
            }

            Text(appState.t("resources.hint"))
                .font(.caption2)
                .foregroundStyle(.secondary)

            Divider().padding(.vertical, 2)

            HStack {
                Spacer()
                Button(role: .destructive) {
                    confirmClearAll()
                } label: {
                    Text(appState.t("resources.clearAll"))
                        .foregroundStyle(.red)
                }
                .disabled(appState.resources.isEmpty || appState.isClearingResources)
            }
        }
        .onAppear {
            // 进入 tab 时刷新清单（onConnect 已经发过一次，这里覆盖运行中后端可能新加的文件）
            if appState.wsClient.isConnected {
                appState.wsClient.sendListResources()
            }
        }
    }

    private func confirmClearAll() {
        let alert = NSAlert()
        alert.messageText = appState.t("resources.clearAllConfirm.title")
        alert.informativeText = appState.t("resources.clearAllConfirm.body")
        alert.alertStyle = .warning
        alert.addButton(withTitle: appState.t("resources.clearAll"))
        alert.addButton(withTitle: appState.t("resources.cancel"))
        if alert.runModal() == .alertFirstButtonReturn {
            appState.isClearingResources = true
            appState.wsClient.sendClearResources()
        }
    }
}

private struct ResourceRow: View {
    let file: ResourceFile
    @Bindable var appState: AppState

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: iconName)
                .foregroundStyle(.secondary)
                .frame(width: 20)
            VStack(alignment: .leading, spacing: 2) {
                Text(file.name)
                    .font(.body)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Text(formatSize(file.size))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button(role: .destructive) {
                confirmDelete()
            } label: {
                Image(systemName: "trash")
                    .foregroundStyle(.red)
            }
            .buttonStyle(.borderless)
        }
        .padding(.vertical, 6)
    }

    private var iconName: String {
        switch (file.name as NSString).pathExtension.lowercased() {
        case "pdf": return "doc.richtext"
        case "md": return "doc.text"
        case "txt": return "doc.plaintext"
        default: return "doc"
        }
    }

    private func formatSize(_ bytes: Int64) -> String {
        let kb = Double(bytes) / 1024.0
        if kb < 1024 {
            return String(format: appState.t("resources.size.kb"), kb)
        }
        return String(format: appState.t("resources.size.mb"), kb / 1024.0)
    }

    private func confirmDelete() {
        let alert = NSAlert()
        alert.messageText = String(
            format: appState.t("resources.deleteConfirm.title"), file.name)
        alert.informativeText = appState.t("resources.deleteConfirm.body")
        alert.alertStyle = .warning
        alert.addButton(withTitle: appState.t("resources.delete"))
        alert.addButton(withTitle: appState.t("resources.cancel"))
        if alert.runModal() == .alertFirstButtonReturn {
            appState.wsClient.sendDeleteResource(name: file.name)
        }
    }
}
