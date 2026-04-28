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
            HStack(spacing: 8) {
                Text("回答提示")
                    .font(.caption)
                    .foregroundColor(.orange)
                if appState.isGeneratingSuggestion {
                    ProgressView()
                        .scaleEffect(0.5)
                        .frame(width: 14, height: 14)
                    Text("思考中…")
                        .font(.caption2)
                        .foregroundColor(.gray)
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
                                .foregroundColor(.white)
                                .textSelection(.enabled)
                        }
                        if !s.keyPoints.isEmpty {
                            Text("💡 \(s.keyPoints)")
                                .font(.system(size: 12))
                                .foregroundColor(.yellow.opacity(0.9))
                                .textSelection(.enabled)
                        }
                        if !s.sampleAnswer.isEmpty {
                            Text("🗣️ \(s.sampleAnswer)")
                                .font(.system(size: 12))
                                .foregroundColor(.white.opacity(0.85))
                                .textSelection(.enabled)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 12)
                    .padding(.bottom, 8)
                } else {
                    Text("点击面试官字幕行 → 点击 💡 生成建议；或等待自动触发…")
                        .font(.system(size: 12))
                        .foregroundColor(.gray)
                        .padding(.horizontal, 12)
                        .padding(.bottom, 8)
                }
            }
        }
        .frame(minHeight: 120)
    }

    /// 缺 API key 时的降级提示卡片（橙色 banner）
    private func apiKeyHint(reason: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "key.fill")
                .foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text("\(reason)需配置 API key")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(.white.opacity(0.9))
                Text("打开 Settings (Cmd+,) → API")
                    .font(.caption2)
                    .foregroundColor(.gray)
            }
            Spacer()
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.18))
        .cornerRadius(6)
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
            // 主要内容
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

                // 英文原文：稳定段（半白色）+ 候选段（更淡灰 + 光标）。
                // partial 的稳定段在新 hypothesis 改写时不抖；候选段是漂移区。
                // 文本选择放到 suggestion 区；这里不启用 textSelection 以免吃掉 tap。
                (
                    Text(entry.stableText)
                        .foregroundColor(.white.opacity(entry.isTranscriptFinal ? 0.9 : 0.85))
                    +
                    Text(entry.tentativeText.isEmpty
                         ? ""
                         : (entry.stableText.isEmpty ? "" : " ") + entry.tentativeText)
                        .foregroundColor(.white.opacity(0.5))
                    +
                    Text(entry.isTranscriptFinal ? "" : " ▎")
                        .foregroundColor(.white.opacity(0.5))
                )
                .font(.system(size: 13))

                if !entry.translation.isEmpty || entry.isTranscriptFinal {
                    Text(entry.translation + (entry.isTranslationComplete ? "" : " ▎"))
                        .font(.system(size: 13))
                        .foregroundColor(.yellow.opacity(entry.isTranslationComplete ? 0.9 : 0.6))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            // 💡 按钮：选中 + interviewer，始终渲染（不受 showSpeaker 影响）
            if entry.speaker == "interviewer" {
                Button {
                    onRequestSuggestion?()
                } label: {
                    Image(systemName: "lightbulb.fill")
                        .font(.system(size: 14))
                        .foregroundStyle(isSelected ? .orange : .orange.opacity(0.0))
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
        .background(
            isSelected
            ? Color.orange.opacity(0.12)
            : Color.clear
        )
        .cornerRadius(4)
        .onTapGesture {
            onSelect?()
        }
    }
}
