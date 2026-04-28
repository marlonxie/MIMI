import SwiftUI

struct SettingsView: View {
    @Bindable var appState: AppState

    var body: some View {
        TabView {
            Form {
                Picker("面试语言", selection: $appState.interviewLanguage) {
                    Text("English").tag("en")
                    Text("Deutsch").tag("de")
                }
                Picker("我的母语", selection: $appState.nativeLanguage) {
                    Text("中文").tag("zh")
                    Text("English").tag("en")
                }
                Text("切换会立即推送到后端，无需重启录音。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .tabItem { Label("语言", systemImage: "globe") }
            .padding()

            Form {
                Toggle("启用 RAG 面试提示", isOn: $appState.suggestionEnabled)
                Text("开启后，面试官说完一句 ~3s 会基于你上传的资料自动给出回答参考。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .tabItem { Label("提示", systemImage: "lightbulb") }
            .padding()

            apiKeyTab
                .tabItem { Label("API", systemImage: "key") }
                .padding()
        }
        .frame(width: 460, height: 320)
    }

    // MARK: - API Key tab

    private var apiKeyTab: some View {
        Form {
            Picker("LLM Provider", selection: $appState.llmProvider) {
                Text("Google Gemini").tag("gemini")
                Text("Anthropic Claude").tag("claude")
                Text("本地模型（即将支持）").tag("local_mlx")
            }
            .onChange(of: appState.llmProvider) { _, _ in
                appState.loadApiKeyForCurrentProvider()
            }

            SecureField("API Key", text: $appState.apiKey, prompt: Text("粘贴你的 API key"))
                .textFieldStyle(.roundedBorder)
                .disabled(appState.llmProvider == "local_mlx")

            HStack {
                Button("保存并应用") {
                    appState.applyApiKey()
                }
                .disabled(appState.apiKey.isEmpty || appState.llmProvider == "local_mlx")

                Spacer()

                if appState.translationReady {
                    Label("翻译已就绪", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                        .font(.caption)
                }
            }

            if appState.translationReady && appState.apiKey.isEmpty {
                // backend 已用 .env 配好；用户点这里输入会显式覆盖
                HStack(alignment: .top, spacing: 6) {
                    Image(systemName: "info.circle").foregroundStyle(.blue)
                    Text("后端已通过 .env 配置就绪。在此输入会覆盖 .env 的 key。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Text("Key 仅存 macOS Keychain，本地保存，不上传。")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}
