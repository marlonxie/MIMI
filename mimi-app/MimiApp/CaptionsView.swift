import SwiftUI

/// 字幕区：滚动的 TranslationRow 列表。iOS 聊天风：speaker pill + 行内分隔。
struct CaptionsView: View {
    @Bindable var appState: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(appState.t("captions.header"))
                    .font(Theme.headerFont)
                    .foregroundColor(Theme.labelSecondary)
                Spacer()
                Text(String(format: appState.t("captions.count"), appState.translations.count))
                    .font(.caption2)
                    .foregroundColor(Theme.labelTertiary)
            }
            .padding(.horizontal, 12)
            .padding(.top, 8)

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(appState.translations.enumerated()), id: \.element.id) { index, entry in
                            let prevSpeaker = index > 0 ? appState.translations[index - 1].speaker : nil
                            let showSpeaker = entry.speaker != prevSpeaker

                            TranslationRow(
                                entry: entry,
                                showSpeaker: showSpeaker,
                                isFirstInGroup: showSpeaker,
                                isFirstRow: index == 0,
                                isSelected: entry.id == appState.selectedSentenceId,
                                speakerLabel: speakerLabel(for: entry.speaker),
                                suggestionTooltip: appState.t("captions.suggestion.tip"),
                                onSelect: { appState.selectSentence(entry.id) },
                                onRequestSuggestion: { appState.requestSuggestion(sentenceId: entry.id) }
                            )
                            .id(entry.id)
                        }
                    }
                    .padding(.horizontal, 8)
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
    }

    private func speakerLabel(for speaker: String) -> String {
        speaker == "interviewer"
            ? appState.t("captions.speaker.interviewer")
            : appState.t("captions.speaker.me")
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        if let last = appState.translations.last {
            withAnimation(.easeOut(duration: 0.15)) {
                proxy.scrollTo(last.id, anchor: .bottom)
            }
        }
    }
}

// MARK: - Speaker chip (iOS pill)

private struct SpeakerChip: View {
    let label: String
    let speaker: String   // "interviewer" | "me"

    var body: some View {
        let tint = speaker == "interviewer" ? Theme.systemBlue : Theme.systemGreen
        Text(label.uppercased())
            .font(Theme.chipFont)
            .tracking(0.4)
            .foregroundStyle(tint)
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .background(
                Capsule(style: .continuous)
                    .fill(tint.opacity(0.18))
            )
    }
}

// MARK: - Translation Row

struct TranslationRow: View {
    @Bindable var entry: TranslationEntry
    var showSpeaker: Bool = true
    var isFirstInGroup: Bool = false
    var isFirstRow: Bool = false
    var isSelected: Bool = false
    var speakerLabel: String = ""
    var suggestionTooltip: String = ""
    var onSelect: (() -> Void)? = nil
    var onRequestSuggestion: (() -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if isFirstInGroup && !isFirstRow {
                Rectangle()
                    .fill(Theme.separator)
                    .frame(height: 1)
                    .padding(.horizontal, 4)
                    .padding(.vertical, 6)
            }

            HStack(alignment: .top, spacing: 8) {
                VStack(alignment: .leading, spacing: 4) {
                    if showSpeaker {
                        HStack(spacing: 6) {
                            SpeakerChip(label: speakerLabel, speaker: entry.speaker)
                            Text(entry.timestamp)
                                .font(.caption2)
                                .foregroundColor(Theme.labelTertiary)
                            Spacer()
                        }
                    }

                    // 原文：稳定段（亮）+ 候选段（更淡 + 光标）
                    (
                        Text(entry.stableText)
                            .foregroundColor(Theme.labelPrimary)
                        +
                        Text(entry.tentativeText.isEmpty
                             ? ""
                             : (entry.stableText.isEmpty ? "" : " ") + entry.tentativeText)
                            .foregroundColor(Theme.labelTertiary)
                        +
                        Text(entry.isTranscriptFinal ? "" : " ▎")
                            .foregroundColor(Theme.labelTertiary)
                    )
                    .font(Theme.bodyFont)

                    if !entry.translation.isEmpty || entry.isTranscriptFinal {
                        Text(entry.translation + (entry.isTranslationComplete ? "" : " ▎"))
                            .font(Theme.bodyFont)
                            .foregroundColor(entry.isTranslationComplete
                                ? Theme.labelSecondary
                                : Theme.labelSecondary.opacity(0.6))
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                // 💡 选中即可点（任一 speaker）；manual_suggest 后端对 speaker 无要求
                Button {
                    onRequestSuggestion?()
                } label: {
                    Image(systemName: "lightbulb.fill")
                        .font(.system(size: 13, weight: .regular))
                        .foregroundStyle(isSelected ? .white : .clear)
                        .frame(width: 24, height: 24)
                        .background(isSelected ? Theme.systemBlue : Color.clear)
                        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.button,
                                                    style: .continuous))
                }
                .buttonStyle(.plain)
                .disabled(!isSelected)
                .help(suggestionTooltip)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .contentShape(Rectangle())
            .background(isSelected ? Theme.systemBlue.opacity(0.12) : Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.button, style: .continuous))
            .onTapGesture {
                onSelect?()
            }
        }
    }
}

// MARK: - Previews

#Preview("captions - 空") {
    ZStack {
        Theme.panelBaseSolid
        CaptionsView(appState: AppState())
    }
    .frame(width: 480, height: 240)
}

#Preview("captions - 多句对话") {
    let s: AppState = {
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
        return s
    }()
    ZStack {
        Theme.panelBaseSolid
        CaptionsView(appState: s)
    }
    .frame(width: 480, height: 240)
}
