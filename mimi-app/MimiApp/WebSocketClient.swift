import Foundation

@MainActor
@Observable
class WebSocketClient {
    var isConnected = false
    var onTranscript: (@MainActor (TranscriptMessage) -> Void)?
    var onTranslationDelta: (@MainActor (TranslationDeltaMessage) -> Void)?
    var onTranslationFinal: (@MainActor (TranslationFinalMessage) -> Void)?
    var onSuggestion: (@MainActor (SuggestionMessage) -> Void)?

    private var webSocket: URLSessionWebSocketTask?
    private var session: URLSession?
    private let url: URL
    private var reconnectAttempts = 0
    private let maxReconnectAttempts = 10

    init(url: URL = URL(string: "ws://127.0.0.1:8765/ws")!) {
        self.url = url
    }

    func connect() {
        // 清理旧的 session（如果有）
        session?.invalidateAndCancel()

        let delegate = WebSocketDelegate { [weak self] in
            Task { @MainActor in
                self?.isConnected = true
                self?.reconnectAttempts = 0
                print("WebSocket 已连接")
            }
        } onClose: { [weak self] in
            Task { @MainActor in
                self?.isConnected = false
                print("WebSocket 已断开")
                // 不在这里重连，由 receiveMessage 失败统一触发
            }
        }
        session = URLSession(configuration: .default, delegate: delegate, delegateQueue: nil)
        webSocket = session?.webSocketTask(with: url)
        webSocket?.resume()
        receiveMessage()
    }

    func disconnect() {
        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil
        isConnected = false
    }

    func sendConfig(source: String) {
        sendJSON(ConfigMessage(source: source))
    }

    /// 发送音频数据，source 嵌入消息本身（前 1 字节：0x00=interviewer, 0x01=me）
    func sendAudio(_ data: Data, source: String) {
        guard isConnected else { return }
        var payload = Data([source == "me" ? 0x01 : 0x00])
        payload.append(data)
        webSocket?.send(.data(payload)) { @Sendable error in
            if let error { print("音频发送失败: \(error)") }
        }
    }

    func sendExport() { sendJSON(ControlMessage.export) }
    func sendFlush() { sendJSON(ControlMessage.flush) }
    func sendLanguages(interview: String, native: String) {
        sendJSON(LanguageConfigMessage(interview: interview, native: native))
    }
    func sendSuggestionEnabled(_ enabled: Bool) {
        sendJSON(SuggestionConfigMessage(enabled: enabled))
    }
    func sendManualSuggest(sentenceId: String) {
        sendJSON(ManualSuggestMessage(sentenceId: sentenceId))
    }

    // MARK: - Receive

    private func receiveMessage() {
        webSocket?.receive { [weak self] result in
            guard let self else { return }
            Task { @MainActor [weak self] in
                guard let self else { return }
                switch result {
                case .success(let message):
                    self.handleMessage(message)
                    self.receiveMessage()
                case .failure(let error):
                    print("WebSocket 接收错误: \(error)")
                    self.isConnected = false
                    self.attemptReconnect()
                }
            }
        }
    }

    private func handleMessage(_ message: URLSessionWebSocketTask.Message) {
        let data: Data
        switch message {
        case .string(let text):
            guard let d = text.data(using: .utf8) else { return }
            data = d
        case .data(let d):
            data = d
        @unknown default:
            return
        }

        guard let base = try? JSONDecoder().decode(ServerMessage.self, from: data) else { return }

        switch base.type {
        case "transcript":
            if let msg = try? JSONDecoder().decode(TranscriptMessage.self, from: data) {
                onTranscript?(msg)
            }
        case "translation_delta":
            if let msg = try? JSONDecoder().decode(TranslationDeltaMessage.self, from: data) {
                onTranslationDelta?(msg)
            }
        case "translation_final":
            if let msg = try? JSONDecoder().decode(TranslationFinalMessage.self, from: data) {
                onTranslationFinal?(msg)
            }
        case "suggestion":
            if let msg = try? JSONDecoder().decode(SuggestionMessage.self, from: data) {
                onSuggestion?(msg)
            }
        default:
            break
        }
    }

    private func attemptReconnect() {
        // 防止并发重连：如果已经在重连或已连接，跳过
        guard !isConnected, reconnectAttempts < maxReconnectAttempts else { return }
        reconnectAttempts += 1
        let delay = min(pow(2.0, Double(reconnectAttempts)), 30.0)
        let attempt = reconnectAttempts
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard let self, !self.isConnected else { return }
            print("重连中... (第 \(attempt) 次)")
            self.connect()
        }
    }

    private func sendJSON<T: Encodable>(_ value: T) {
        guard isConnected,
              let data = try? JSONEncoder().encode(value),
              let text = String(data: data, encoding: .utf8) else { return }
        // JSON 必须作为 text 发送，Python 服务端用 "text" in message 判断
        webSocket?.send(.string(text)) { @Sendable error in
            if let error { print("JSON 发送失败: \(error)") }
        }
    }
}

// MARK: - WebSocket Delegate

private class WebSocketDelegate: NSObject, URLSessionWebSocketDelegate, @unchecked Sendable {
    let onOpen: () -> Void
    let onClose: () -> Void

    init(onOpen: @escaping () -> Void, onClose: @escaping () -> Void) {
        self.onOpen = onOpen
        self.onClose = onClose
    }

    func urlSession(_ session: URLSession,
                    webSocketTask: URLSessionWebSocketTask,
                    didOpenWithProtocol protocol: String?) {
        onOpen()
    }

    func urlSession(_ session: URLSession,
                    webSocketTask: URLSessionWebSocketTask,
                    didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
                    reason: Data?) {
        onClose()
    }
}
