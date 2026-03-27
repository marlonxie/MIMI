import Foundation

// MARK: - Server Messages

struct ServerMessage: Codable {
    let type: String
}

struct TranslationMessage: Codable {
    let type: String
    let speaker: String
    let original: String
    let language: String
    let translation: String
    let timestamp: String
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

// MARK: - App State

struct TranslationEntry: Identifiable {
    let id = UUID()
    let speaker: String
    let original: String
    let translation: String
    let timestamp: String

    var speakerLabel: String {
        speaker == "interviewer" ? "面试官" : "我"
    }
}
