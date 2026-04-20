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
        }
        .frame(width: 420, height: 240)
    }
}
