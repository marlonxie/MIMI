import Foundation

// MARK: - Server Messages

struct ServerMessage: Codable {
    let type: String
}

/// 英文识别结果（is_final 区分最终/部分）。Phase A 只发 is_final=true，Phase B 会发 partial。
struct TranscriptMessage: Codable {
    let type: String
    let sentenceId: String
    let speaker: String
    let language: String
    let text: String
    let isFinal: Bool
    let timestamp: String
    let insertAfter: String?  // 多句拆分时，告诉前端插到哪个 ID 后面

    enum CodingKeys: String, CodingKey {
        case type
        case sentenceId = "sentence_id"
        case speaker
        case language
        case text
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

// MARK: - App State

/// 一行字幕。class + @Observable，按 sentenceId 索引，字段可被流式增量更新。
/// 不显式标 @MainActor — 由调用方（AppState 是 @MainActor）保证只在主线程访问。
@Observable
final class TranslationEntry: Identifiable {
    let id: String              // = sentenceId，用于 ForEach / ScrollViewReader
    let speaker: String
    let timestamp: String
    var original: String        // 英文，partial 时可能被更新
    var translation: String     // 中文，translation_delta 追加，translation_final 定型
    var isTranscriptFinal: Bool // false = partial（半透明）
    var isTranslationComplete: Bool

    init(
        sentenceId: String,
        speaker: String,
        timestamp: String,
        original: String,
        translation: String = "",
        isTranscriptFinal: Bool = true,
        isTranslationComplete: Bool = false
    ) {
        self.id = sentenceId
        self.speaker = speaker
        self.timestamp = timestamp
        self.original = original
        self.translation = translation
        self.isTranscriptFinal = isTranscriptFinal
        self.isTranslationComplete = isTranslationComplete
    }

    var speakerLabel: String {
        speaker == "interviewer" ? "面试官" : "我"
    }
}
