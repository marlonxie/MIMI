import SwiftUI

/// 回答提示区。从原 OverlayWindow suggestionSection 提取，仅迁移 + 改色（结构不变）。
struct SuggestionView: View {
    @Bindable var appState: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Text("回答提示")
                    .font(.caption)
                    .foregroundColor(Theme.warningAccent)
                if appState.isGeneratingSuggestion {
                    ProgressView()
                        .scaleEffect(0.5)
                        .frame(width: 14, height: 14)
                    Text("思考中…")
                        .font(.caption2)
                        .foregroundColor(Theme.textMuted)
                }
                Spacer()
            }
            .padding(.horizontal, 12)
            .padding(.top, 8)

            ScrollView {
                // 优先级：未就绪降级提示 > suggestion 内容 > 默认占位
                if !appState.translationReady {
                    apiKeyHint(reason: "启用翻译")
                        .padding(.horizontal, 12)
                        .padding(.bottom, 8)
                } else if appState.ragLoaded && !appState.ragReady {
                    apiKeyHint(reason: "启用 AI 回答提示")
                        .padding(.horizontal, 12)
                        .padding(.bottom, 8)
                } else if let s = appState.currentSuggestion {
                    VStack(alignment: .leading, spacing: 8) {
                        if !s.understanding.isEmpty {
                            Text("📌 \(s.understanding)")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundColor(Theme.textPrimary)
                                .textSelection(.enabled)
                        }
                        if !s.keyPoints.isEmpty {
                            Text("💡 \(s.keyPoints)")
                                .font(.system(size: 12))
                                .foregroundColor(Theme.warningAccent.opacity(0.95))
                                .textSelection(.enabled)
                        }
                        if !s.sampleAnswer.isEmpty {
                            Text("🗣️ \(s.sampleAnswer)")
                                .font(.system(size: 12))
                                .foregroundColor(Theme.textSecondary)
                                .textSelection(.enabled)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 12)
                    .padding(.bottom, 8)
                } else {
                    Text("点击面试官字幕行 → 点击 💡 生成建议；或等待自动触发…")
                        .font(.system(size: 12))
                        .foregroundColor(Theme.textMuted)
                        .padding(.horizontal, 12)
                        .padding(.bottom, 8)
                }
            }
        }
        .frame(minWidth: 360, minHeight: 120)
        .background(Theme.panelBackground)
    }

    /// 缺 API key 时的降级提示卡片（橙色 banner）
    private func apiKeyHint(reason: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "key.fill")
                .foregroundStyle(Theme.warningAccent)
            VStack(alignment: .leading, spacing: 2) {
                Text("\(reason)需配置 API key")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(Theme.textPrimary)
                Text("打开 Settings (Cmd+,) → API")
                    .font(.caption2)
                    .foregroundColor(Theme.textMuted)
            }
            Spacer()
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.warningAccent.opacity(0.18))
        .cornerRadius(6)
    }
}
