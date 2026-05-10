import Foundation

// MARK: - Server Messages

struct ServerMessage: Codable {
    let type: String
}

/// 英文识别结果（is_final 区分最终/部分）。Phase A 只发 is_final=true，Phase B 会发 partial。
/// partial 消息后端会同时发 stable_text + tentative_text 双段，前端按稳定性分别渲染。
/// 旧 server 不发这两个字段时为 nil，前端 fallback 到 text。
struct TranscriptMessage: Codable {
    let type: String
    let sentenceId: String
    let speaker: String
    let language: String
    let text: String
    let stableText: String?      // 已 confirmed 的稳定段（segmenter pending），永不变
    let tentativeText: String?   // Whisper 还在猜的段（stream tentative），可能漂移
    let isFinal: Bool
    let timestamp: String
    let insertAfter: String?  // 多句拆分时，告诉前端插到哪个 ID 后面

    enum CodingKeys: String, CodingKey {
        case type
        case sentenceId = "sentence_id"
        case speaker
        case language
        case text
        case stableText = "stable_text"
        case tentativeText = "tentative_text"
        case isFinal = "is_final"
        case timestamp
        case insertAfter = "insert_after"
    }
}

/// 中文翻译流式 token 增量
struct TranslationDeltaMessage: Codable {
    let type: String
    let sentenceId: String
    let delta: String

    enum CodingKeys: String, CodingKey {
        case type
        case sentenceId = "sentence_id"
        case delta
    }
}

/// 中文翻译完成
struct TranslationFinalMessage: Codable {
    let type: String
    let sentenceId: String
    let text: String

    enum CodingKeys: String, CodingKey {
        case type
        case sentenceId = "sentence_id"
        case text
    }
}

struct SuggestionMessage: Codable {
    let type: String
    let suggestion: String
    let sources: [String]
}

struct ConfigAckMessage: Codable {
    let type: String
    let source: String
}

/// 后端导出对话记录后回的 ack：path = 真正写入的绝对路径
struct ExportAckMessage: Codable {
    let type: String
    let path: String
}

/// 后端 rebuild_index 完成后回的 ack：count = 索引到的源文件数；error 失败时才有
struct RebuildIndexAckMessage: Codable {
    let type: String
    let count: Int
    let error: String?
}

/// 已上传参考资料一项
struct ResourceFile: Codable, Identifiable, Hashable {
    let name: String
    let size: Int64
    let mtime: Double
    var id: String { name }
}

/// list_resources 的回应
struct ResourcesListMessage: Codable {
    let type: String
    let files: [ResourceFile]
}

/// delete_resource 的回应；ok=true 时 remaining 是删后的总数
struct DeleteResourceAckMessage: Codable {
    let type: String
    let ok: Bool
    let remaining: Int?
    let error: String?
}

/// clear_resources 的回应（无需 payload）
struct ClearResourcesAckMessage: Codable {
    let type: String
}

// MARK: - Client Messages

struct ConfigMessage: Codable {
    let type: String
    let source: String

    init(source: String) {
        self.type = "config"
        self.source = source
    }
}

struct ControlMessage: Codable {
    let type: String

    static let export = ControlMessage(type: "export")
    static let flush = ControlMessage(type: "flush")
}

struct LanguageConfigMessage: Codable {
    let type: String
    let interviewLanguage: String
    let nativeLanguage: String

    init(interview: String, native: String) {
        self.type = "set_languages"
        self.interviewLanguage = interview
        self.nativeLanguage = native
    }

    enum CodingKeys: String, CodingKey {
        case type
        case interviewLanguage = "interview_language"
        case nativeLanguage = "native_language"
    }
}

struct SuggestionConfigMessage: Codable {
    let type: String
    let enabled: Bool

    init(enabled: Bool) {
        self.type = "set_suggestion_enabled"
        self.enabled = enabled
    }
}

struct ManualSuggestMessage: Codable {
    let type: String
    let sentenceId: String

    init(sentenceId: String) {
        self.type = "manual_suggest"
        self.sentenceId = sentenceId
    }

    enum CodingKeys: String, CodingKey {
        case type
        case sentenceId = "sentence_id"
    }
}

// MARK: - API Key 协议消息

struct ApiKeysMessage: Codable {
    let type: String
    let provider: String   // "gemini" | "claude"
    let apiKey: String

    init(provider: String, apiKey: String) {
        self.type = "set_api_keys"
        self.provider = provider
        self.apiKey = apiKey
    }

    enum CodingKeys: String, CodingKey {
        case type
        case provider
        case apiKey = "api_key"
    }
}

struct ApiKeysAckMessage: Codable {
    let type: String
    let provider: String
    let translatorReady: Bool
    let ragReady: Bool

    enum CodingKeys: String, CodingKey {
        case type
        case provider
        case translatorReady = "translator_ready"
        case ragReady = "rag_ready"
    }
}

struct StatusQueryMessage: Codable {
    let type: String

    init() { self.type = "query_status" }
}

struct StatusMessage: Codable {
    let type: String
    let activeProvider: String
    let translatorReady: Bool
    let ragReady: Bool
    let ragLoaded: Bool

    enum CodingKeys: String, CodingKey {
        case type
        case activeProvider = "active_provider"
        case translatorReady = "translator_ready"
        case ragReady = "rag_ready"
        case ragLoaded = "rag_loaded"
    }
}

/// 三段式 suggestion 的客户端解析（按 📌 / 💡 / 🗣️ emoji 前缀拆分）。
/// 后端 RAG prompt 强制输出这三段，前端在此分段便于 UI 分层渲染。
struct ParsedSuggestion {
    let understanding: String   // 📌 后
    let keyPoints: String       // 💡 后
    let sampleAnswer: String    // 🗣️ 后

    static func parse(_ raw: String) -> ParsedSuggestion {
        let markers = ["📌", "💡", "🗣️"]

        func extract(_ marker: String) -> String {
            guard let startRange = raw.range(of: marker) else { return "" }
            let after = raw[startRange.upperBound...]
            // 下一个 marker 的起点（不含当前 marker）
            let nextStart: String.Index = markers
                .filter { $0 != marker }
                .compactMap { after.range(of: $0)?.lowerBound }
                .min() ?? after.endIndex
            var body = String(after[..<nextStart])
            // 去掉 markdown 样式的 `**标题**\n` 前缀（常见格式："📌 **问题理解**\n..."）
            body = body.trimmingCharacters(in: .whitespacesAndNewlines)
            if body.hasPrefix("**") {
                if let closeRange = body.range(of: "**", range: body.index(body.startIndex, offsetBy: 2)..<body.endIndex) {
                    body = String(body[closeRange.upperBound...])
                        .trimmingCharacters(in: .whitespacesAndNewlines)
                }
            }
            return body
        }

        return ParsedSuggestion(
            understanding: extract("📌"),
            keyPoints: extract("💡"),
            sampleAnswer: extract("🗣️")
        )
    }

    /// 如果三段都空，fallback 把整段原文塞进 understanding
    static func parseOrFallback(_ raw: String) -> ParsedSuggestion {
        let parsed = parse(raw)
        if parsed.understanding.isEmpty && parsed.keyPoints.isEmpty && parsed.sampleAnswer.isEmpty {
            return ParsedSuggestion(
                understanding: raw.trimmingCharacters(in: .whitespacesAndNewlines),
                keyPoints: "",
                sampleAnswer: ""
            )
        }
        return parsed
    }
}

// MARK: - App State

/// 一行字幕。class + @Observable，按 sentenceId 索引，字段可被流式增量更新。
/// 不显式标 @MainActor — 由调用方（AppState 是 @MainActor）保证只在主线程访问。
@Observable
final class TranslationEntry: Identifiable {
    let id: String              // = sentenceId，用于 ForEach / ScrollViewReader
    let speaker: String
    let timestamp: String
    var original: String        // 完整英文（兼容字段；= stableText + tentativeText 拼接）
    var stableText: String      // 已 confirmed 的稳定段（半白色，无光标）
    var tentativeText: String   // Whisper 还在猜的段（更淡灰 + 光标 ▎）；final 时为空
    var translation: String     // 中文，translation_delta 追加，translation_final 定型
    var isTranscriptFinal: Bool // false = partial（半透明）
    var isTranslationComplete: Bool

    init(
        sentenceId: String,
        speaker: String,
        timestamp: String,
        original: String,
        stableText: String = "",
        tentativeText: String = "",
        translation: String = "",
        isTranscriptFinal: Bool = true,
        isTranslationComplete: Bool = false
    ) {
        self.id = sentenceId
        self.speaker = speaker
        self.timestamp = timestamp
        self.original = original
        self.stableText = stableText
        self.tentativeText = tentativeText
        self.translation = translation
        self.isTranscriptFinal = isTranscriptFinal
        self.isTranslationComplete = isTranslationComplete
    }

    var speakerLabel: String {
        speaker == "interviewer" ? "面试官" : "我"
    }
}
