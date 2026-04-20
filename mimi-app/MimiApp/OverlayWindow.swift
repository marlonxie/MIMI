import SwiftUI

struct OverlayWindowContent: View {
    @Bindable var appState: AppState

    var body: some View {
        VStack(spacing: 0) {
            if appState.isCapturing {
                controlBar
            }
            VSplitView {
                // 翻译区
                translationSection

                // 提示区
                suggestionSection
            }
        }
        .frame(minWidth: 450, minHeight: 300)
        .background(Color.black.opacity(0.85))
    }

    // MARK: - 控制条（录音中才显示）

    private var controlBar: some View {
        HStack(spacing: 16) {
            // 麦克风开关
            Button {
                Task { await appState.toggleMicrophone() }
            } label: {
                Image(systemName: appState.isMicrophoneEnabled ? "mic.fill" : "mic.slash.fill")
                    .font(.system(size: 14))
                    .foregroundStyle(appState.isMicrophoneEnabled ? .white : .red)
            }
            .buttonStyle(.plain)
            .help(appState.isMicrophoneEnabled ? "关闭麦克风" : "开启麦克风")

            // 屏幕录制开关（系统音频 = 面试官那一路）
            Button {
                Task { await appState.toggleSystemAudio() }
            } label: {
                Image(systemName: appState.isSystemAudioEnabled ? "speaker.wave.2.fill" : "speaker.slash.fill")
                    .font(.system(size: 14))
                    .foregroundStyle(appState.isSystemAudioEnabled ? .white : .red)
            }
            .buttonStyle(.plain)
            .help(appState.isSystemAudioEnabled ? "关闭屏幕录制" : "开启屏幕录制")

            Spacer()

            Text(statusText)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(Color.black.opacity(0.35))
    }

    private var statusText: String {
        switch (appState.isMicrophoneEnabled, appState.isSystemAudioEnabled) {
        case (true, true):   return "双路录音"
        case (true, false):  return "仅麦克风"
        case (false, true):  return "仅屏幕录制"
        case (false, false): return "静音中"
        }
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
                    LazyVStack(alignment: .leading, spacing: 4) {
                        ForEach(Array(appState.translations.enumerated()), id: \.element.id) { index, entry in
                            let prevSpeaker = index > 0 ? appState.translations[index - 1].speaker : nil
                            let showSpeaker = entry.speaker != prevSpeaker

                            TranslationRow(entry: entry, showSpeaker: showSpeaker)
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
        .frame(minHeight: 150)
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        if let last = appState.translations.last {
            withAnimation(.easeOut(duration: 0.15)) {
                proxy.scrollTo(last.id, anchor: .bottom)
            }
        }
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
    var showSpeaker: Bool = true

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            // 说话人标签：只在 speaker 切换时显示
            if showSpeaker {
                HStack(spacing: 4) {
                    Text(entry.speakerLabel)
                        .font(.caption2)
                        .foregroundColor(entry.speaker == "interviewer" ? .cyan : .green)
                        .fontWeight(.bold)
                    Text(entry.timestamp)
                        .font(.caption2)
                        .foregroundColor(.gray)
                }
            }

            // 英文原文 + 中文翻译：始终分行显示
            Text(entry.original + (entry.isTranscriptFinal ? "" : " ▎"))
                .font(.system(size: 13))
                .foregroundColor(.white.opacity(entry.isTranscriptFinal ? 0.9 : 0.5))
                .textSelection(.enabled)
            if !entry.translation.isEmpty || entry.isTranscriptFinal {
                Text(entry.translation + (entry.isTranslationComplete ? "" : " ▎"))
                    .font(.system(size: 13))
                    .foregroundColor(.yellow.opacity(entry.isTranslationComplete ? 0.9 : 0.6))
                    .textSelection(.enabled)
            }
        }
    }
}
