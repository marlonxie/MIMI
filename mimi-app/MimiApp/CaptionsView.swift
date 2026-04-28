import SwiftUI

/// 字幕区：滚动的 TranslationRow 列表。从原 OverlayWindow translationSection 提取。
struct CaptionsView: View {
    @Bindable var appState: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("翻译")
                    .font(.caption)
                    .foregroundColor(Theme.textMuted)
                Spacer()
                Text("\(appState.translations.count) 条")
                    .font(.caption2)
                    .foregroundColor(Theme.textMuted)
            }
            .padding(.horizontal, 12)
            .padding(.top, 8)

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 4) {
                        ForEach(Array(appState.translations.enumerated()), id: \.element.id) { index, entry in
                            let prevSpeaker = index > 0 ? appState.translations[index - 1].speaker : nil
                            let showSpeaker = entry.speaker != prevSpeaker

                            TranslationRow(
                                entry: entry,
                                showSpeaker: showSpeaker,
                                isSelected: entry.id == appState.selectedSentenceId,
                                onSelect: { appState.selectSentence(entry.id) },
                                onRequestSuggestion: { appState.requestSuggestion(sentenceId: entry.id) }
                            )
                            .id(entry.id)
                            .padding(.top, showSpeaker && index > 0 ? 12 : 0)
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.bottom, 8)
                }
                .onChange(of: appState.translations.count) {
                    scrollToBottom(proxy)
                }
                .onChange(of: appState.translations.last?.original) {
                    scrollToBottom(proxy)
                }
            }
        }
        .frame(minWidth: 360, minHeight: 150)
        .background(Theme.panelBackground)
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        if let last = appState.translations.last {
            withAnimation(.easeOut(duration: 0.15)) {
                proxy.scrollTo(last.id, anchor: .bottom)
            }
        }
    }
}

// MARK: - Translation Row

struct TranslationRow: View {
    @Bindable var entry: TranslationEntry
    var showSpeaker: Bool = true
    var isSelected: Bool = false
    var onSelect: (() -> Void)? = nil
    var onRequestSuggestion: (() -> Void)? = nil

    var body: some View {
        HStack(alignment: .top, spacing: 6) {
            VStack(alignment: .leading, spacing: 2) {
                // speaker 标签：只在 speaker 切换时显示
                if showSpeaker {
                    HStack(spacing: 4) {
                        Text(entry.speakerLabel)
                            .font(.caption2)
                            .foregroundColor(entry.speaker == "interviewer"
                                ? Theme.interviewerAccent : Theme.meAccent)
                            .fontWeight(.bold)
                        Text(entry.timestamp)
                            .font(.caption2)
                            .foregroundColor(Theme.textMuted)
                    }
                }

                // 原文：稳定段（亮）+ 候选段（淡灰 + 光标）
                (
                    Text(entry.stableText)
                        .foregroundColor(entry.isTranscriptFinal ? Theme.textPrimary : Theme.textPrimary.opacity(0.92))
                    +
                    Text(entry.tentativeText.isEmpty
                         ? ""
                         : (entry.stableText.isEmpty ? "" : " ") + entry.tentativeText)
                        .foregroundColor(Theme.textTertiary)
                    +
                    Text(entry.isTranscriptFinal ? "" : " ▎")
                        .foregroundColor(Theme.textTertiary)
                )
                .font(.system(size: 13))

                if !entry.translation.isEmpty || entry.isTranscriptFinal {
                    Text(entry.translation + (entry.isTranslationComplete ? "" : " ▎"))
                        .font(.system(size: 13))
                        .foregroundColor(entry.isTranslationComplete
                            ? Theme.translationColor
                            : Theme.translationColor.opacity(0.6))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            // 💡 按钮：选中 + interviewer
            if entry.speaker == "interviewer" {
                Button {
                    onRequestSuggestion?()
                } label: {
                    Image(systemName: "lightbulb.fill")
                        .font(.system(size: 14))
                        .foregroundStyle(isSelected ? Theme.warningAccent : Theme.warningAccent.opacity(0.0))
                        .frame(width: 20, height: 20)
                }
                .buttonStyle(.plain)
                .disabled(!isSelected)
                .help("为这句生成回答建议")
            }
        }
        .padding(.vertical, 2)
        .padding(.horizontal, 4)
        .contentShape(Rectangle())
        .background(isSelected ? Theme.warningAccent.opacity(0.12) : Color.clear)
        .cornerRadius(4)
        .onTapGesture {
            onSelect?()
        }
    }
}

// MARK: - Previews

#Preview("captions - 空") {
    CaptionsView(appState: AppState())
        .frame(width: 480, height: 240)
}

#Preview("captions - 多句对话") {
    let s = AppState()
    let e1 = TranslationEntry(
        sentenceId: "1", speaker: "interviewer", timestamp: "12:00:01",
        original: "Tell me about yourself.",
        stableText: "Tell me about yourself.", tentativeText: "",
        translation: "请简单介绍一下你自己。",
        isTranscriptFinal: true, isTranslationComplete: true
    )
    let e2 = TranslationEntry(
        sentenceId: "2", speaker: "me", timestamp: "12:00:08",
        original: "Sure, I'm a software engineer.",
        stableText: "Sure, I'm a software engineer.", tentativeText: "",
        translation: "好的，我是一名软件工程师。",
        isTranscriptFinal: true, isTranslationComplete: true
    )
    let e3 = TranslationEntry(
        sentenceId: "3", speaker: "interviewer", timestamp: "12:00:15",
        original: "What's your favorite project",
        stableText: "What's your favorite", tentativeText: "project",
        translation: "你最喜欢的",
        isTranscriptFinal: false, isTranslationComplete: false
    )
    s.translations = [e1, e2, e3]
    s.selectedSentenceId = "3"
    return CaptionsView(appState: s)
        .frame(width: 480, height: 240)
}
