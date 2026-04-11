import SwiftUI

struct OverlayWindowContent: View {
    @Bindable var appState: AppState

    var body: some View {
        VSplitView {
            // 翻译区
            translationSection

            // 提示区
            suggestionSection
        }
        .frame(minWidth: 450, minHeight: 300)
        .background(Color.black.opacity(0.85))
    }

    // MARK: - 翻译区

    private var translationSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("翻译")
                    .font(.caption)
                    .foregroundColor(.gray)
                Spacer()
                Text("\(appState.translations.count) 条")
                    .font(.caption2)
                    .foregroundColor(.gray)
            }
            .padding(.horizontal, 12)
            .padding(.top, 8)

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 6) {
                        ForEach(appState.translations) { entry in
                            TranslationRow(entry: entry)
                                .id(entry.id)
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.bottom, 8)
                }
                .onChange(of: appState.translations.count) {
                    if let last = appState.translations.last {
                        withAnimation {
                            proxy.scrollTo(last.id, anchor: .bottom)
                        }
                    }
                }
            }
        }
        .frame(minHeight: 150)
    }

    // MARK: - 提示区

    private var suggestionSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("回答提示")
                    .font(.caption)
                    .foregroundColor(.orange)
                Spacer()
            }
            .padding(.horizontal, 12)
            .padding(.top, 8)

            ScrollView {
                if let suggestion = appState.currentSuggestion {
                    Text(suggestion)
                        .font(.system(size: 13))
                        .foregroundColor(.white)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 12)
                        .padding(.bottom, 8)
                } else {
                    Text("等待面试官提问...")
                        .font(.system(size: 13))
                        .foregroundColor(.gray)
                        .padding(.horizontal, 12)
                        .padding(.bottom, 8)
                }
            }
        }
        .frame(minHeight: 100)
    }
}

// MARK: - Translation Row

struct TranslationRow: View {
    @Bindable var entry: TranslationEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 4) {
                Text(entry.speakerLabel)
                    .font(.caption2)
                    .foregroundColor(entry.speaker == "interviewer" ? .cyan : .green)
                    .fontWeight(.bold)
                Text(entry.timestamp)
                    .font(.caption2)
                    .foregroundColor(.gray)
            }
            // 英文原文：partial 时半透明（Phase B 用），final 时正常亮度
            Text(entry.original + (entry.isTranscriptFinal ? "" : " ▎"))
                .font(.system(size: 13))
                .foregroundColor(.white.opacity(entry.isTranscriptFinal ? 0.9 : 0.5))
                .animation(.easeInOut(duration: 0.15), value: entry.isTranscriptFinal)
            // 中文翻译：流式过程中末尾加光标 + 略浅，完成后切到正常亮度
            if !entry.translation.isEmpty || entry.isTranscriptFinal {
                Text(entry.translation + (entry.isTranslationComplete ? "" : " ▎"))
                    .font(.system(size: 13))
                    .foregroundColor(.yellow.opacity(entry.isTranslationComplete ? 0.9 : 0.6))
                    .animation(.easeInOut(duration: 0.15), value: entry.isTranslationComplete)
            }
        }
    }
}
