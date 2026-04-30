import SwiftUI

/// 回答提示区。iOS 平面三段：理解 / 要点 / 示例回答；缺 key 时显示 iOS notice banner。
struct SuggestionView: View {
    @Bindable var appState: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Text(appState.t("suggestion.header"))
                    .font(Theme.headerFont)
                    .foregroundColor(Theme.labelSecondary)
                if appState.isGeneratingSuggestion {
                    ProgressView()
                        .scaleEffect(0.5)
                        .frame(width: 14, height: 14)
                    Text(appState.t("suggestion.thinking"))
                        .font(.caption2)
                        .foregroundColor(Theme.labelTertiary)
                }
                Spacer()
            }
            .padding(.horizontal, 12)
            .padding(.top, 8)

            ScrollView {
                if !appState.translationReady {
                    apiKeyHint(reason: appState.t("apiKey.reason.translation"))
                        .padding(.horizontal, 12)
                        .padding(.bottom, 8)
                } else if appState.ragLoaded && !appState.ragReady {
                    apiKeyHint(reason: appState.t("apiKey.reason.rag"))
                        .padding(.horizontal, 12)
                        .padding(.bottom, 8)
                } else if let s = appState.currentSuggestion {
                    VStack(alignment: .leading, spacing: 0) {
                        if !s.understanding.isEmpty {
                            section(header: appState.t("suggestion.section.understanding"),
                                    body: s.understanding,
                                    color: Theme.labelPrimary,
                                    weight: .medium)
                        }
                        if !s.keyPoints.isEmpty {
                            sectionDivider()
                            section(header: appState.t("suggestion.section.keyPoints"),
                                    body: s.keyPoints,
                                    color: Theme.systemOrange,
                                    weight: .regular)
                        }
                        if !s.sampleAnswer.isEmpty {
                            sectionDivider()
                            section(header: appState.t("suggestion.section.sampleAnswer"),
                                    body: s.sampleAnswer,
                                    color: Theme.labelSecondary,
                                    weight: .regular)
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.bottom, 8)
                } else {
                    Text(appState.t("suggestion.placeholder"))
                        .font(.system(size: 12))
                        .foregroundColor(Theme.labelTertiary)
                        .padding(.horizontal, 12)
                        .padding(.bottom, 8)
                }
            }
        }
        .frame(minWidth: 360, minHeight: 120)
    }

    // MARK: - Section

    private func section(header: String, body: String,
                         color: Color, weight: Font.Weight) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(header.uppercased())
                .font(.system(size: 10, weight: .semibold))
                .tracking(0.6)
                .foregroundColor(Theme.labelTertiary)
            Text(body)
                .font(.system(size: 13, weight: weight))
                .foregroundColor(color)
                .textSelection(.enabled)
        }
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func sectionDivider() -> some View {
        Rectangle()
            .fill(Theme.separator)
            .frame(height: 1)
    }

    // MARK: - API key banner（iOS notice）

    private func apiKeyHint(reason: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "key.fill")
                .font(.system(size: 14, weight: .regular))
                .foregroundStyle(Theme.systemOrange)
                .frame(width: 20)
            VStack(alignment: .leading, spacing: 2) {
                Text(String(format: appState.t("apiKey.banner.title"), reason))
                    .font(.system(size: 13, weight: .medium))
                    .foregroundColor(Theme.labelPrimary)
                Text(appState.t("apiKey.banner.subtitle"))
                    .font(.caption2)
                    .foregroundColor(Theme.labelSecondary)
            }
            Spacer()
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.systemOrange.opacity(0.18))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

// MARK: - Previews

#Preview("suggestion - 缺 API key") {
    let s: AppState = {
        let s = AppState()
        s.translationReady = false
        return s
    }()
    ZStack {
        Theme.panelBaseSolid
        SuggestionView(appState: s)
    }
    .frame(width: 480, height: 200)
}

#Preview("suggestion - 思考中") {
    let s: AppState = {
        let s = AppState()
        s.translationReady = true
        s.ragLoaded = true
        s.ragReady = true
        s.isGeneratingSuggestion = true
        return s
    }()
    ZStack {
        Theme.panelBaseSolid
        SuggestionView(appState: s)
    }
    .frame(width: 480, height: 200)
}

#Preview("suggestion - 三段式回答") {
    let s: AppState = {
        let s = AppState()
        s.translationReady = true
        s.ragLoaded = true
        s.ragReady = true
        s.currentSuggestion = ParsedSuggestion(
            understanding: "考察项目经历与团队协作",
            keyPoints: "团队规模 → team size · 技术栈 → tech stack · 量化结果 → measurable impact",
            sampleAnswer: "I led a 4-person team building a real-time STT pipeline. We cut latency from 1.8s to 600ms by switching to mlx-whisper and adding LocalAgreement-2 streaming."
        )
        return s
    }()
    ZStack {
        Theme.panelBaseSolid
        SuggestionView(appState: s)
    }
    .frame(width: 480, height: 200)
}

#Preview("suggestion - 默认占位") {
    let s: AppState = {
        let s = AppState()
        s.translationReady = true
        s.ragLoaded = true
        s.ragReady = true
        return s
    }()
    ZStack {
        Theme.panelBaseSolid
        SuggestionView(appState: s)
    }
    .frame(width: 480, height: 200)
}
