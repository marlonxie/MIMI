@preconcurrency import AVFoundation
import ScreenCaptureKit

@MainActor
@Observable
class AudioCaptureManager {
    var isCapturing = false
    var onAudioChunk: (@MainActor (Data, String) -> Void)?

    private let targetSampleRate: Double = 16000
    // 1.0s 对应后端 LocalAgreement-2 流式 STT 的更新周期。
    // 改这个值时记得同步改 mimi-backend/config.yaml 的 audio.chunk_duration
    private let chunkDuration: Double = 1.0

    private var audioEngine: AVAudioEngine?
    private var micBuffer = Data()
    private var scStream: SCStream?
    private var systemBuffer = Data()
    private var systemAudioHandler: SystemAudioOutputHandler?  // 强引用，防止被释放
    private var videoHandler: DiscardVideoHandler?             // 强引用

    // MARK: - Start / Stop

    func startCapture() async throws {
        isCapturing = true
        try startMicrophoneCapture()
        try await startSystemAudioCapture()
    }

    func stopCapture() {
        isCapturing = false
        stopMicrophoneCapture()
        stopSystemAudioCapture()
    }

    // MARK: - Microphone

    private func startMicrophoneCapture() throws {
        audioEngine = AVAudioEngine()
        guard let engine = audioEngine else { return }

        let inputNode = engine.inputNode
        let inputFormat = inputNode.outputFormat(forBus: 0)

        guard let targetFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: targetSampleRate,
            channels: 1,
            interleaved: false
        ) else { return }

        let converter = AVAudioConverter(from: inputFormat, to: targetFormat)
        let chunkBytes = Int(targetSampleRate * chunkDuration) * MemoryLayout<Float>.size

        inputNode.installTap(onBus: 0, bufferSize: 4096, format: inputFormat) {
            [weak self] buffer, _ in
            guard let converter else { return }

            let ratio = targetFormat.sampleRate / inputFormat.sampleRate
            let outputFrameCount = AVAudioFrameCount(Double(buffer.frameLength) * ratio)
            guard let outputBuffer = AVAudioPCMBuffer(
                pcmFormat: targetFormat, frameCapacity: outputFrameCount
            ) else { return }

            var error: NSError?
            let inputBuffer = buffer
            converter.convert(to: outputBuffer, error: &error) { _, outStatus in
                outStatus.pointee = .haveData
                return inputBuffer
            }

            guard error == nil, let floatData = outputBuffer.floatChannelData else { return }
            let byteCount = Int(outputBuffer.frameLength) * MemoryLayout<Float>.size
            let chunk = Data(bytes: floatData[0], count: byteCount)

            Task { @MainActor [weak self] in
                guard let self else { return }
                self.micBuffer.append(chunk)
                if self.micBuffer.count >= chunkBytes {
                    let sendData = Data(self.micBuffer.prefix(chunkBytes))
                    self.micBuffer.removeFirst(chunkBytes)
                    self.onAudioChunk?(sendData, "me")
                }
            }
        }

        try engine.start()
    }

    private func stopMicrophoneCapture() {
        audioEngine?.inputNode.removeTap(onBus: 0)
        audioEngine?.stop()
        audioEngine = nil
        micBuffer = Data()
    }

    // MARK: - System Audio

    private func startSystemAudioCapture() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(
            false, onScreenWindowsOnly: false
        )
        guard let display = content.displays.first else {
            print("无法获取显示器")
            return
        }

        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.sampleRate = 48000
        config.channelCount = 1
        // 不捕获视频，避免 "stream output NOT found" 错误
        config.width = 1
        config.height = 1
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1) // 最低帧率（1fps）
        config.pixelFormat = kCVPixelFormatType_32BGRA

        let filter = SCContentFilter(display: display, excludingWindows: [])
        let stream = SCStream(filter: filter, configuration: config, delegate: nil)
        scStream = stream

        let chunkBytes = Int(targetSampleRate * chunkDuration) * MemoryLayout<Float>.size

        let outputHandler = SystemAudioOutputHandler { [weak self] (sampleBuffer: CMSampleBuffer) in
            guard let dataBuffer = sampleBuffer.dataBuffer else { return }
            var length = 0
            var dataPointer: UnsafeMutablePointer<Int8>?
            CMBlockBufferGetDataPointer(dataBuffer, atOffset: 0, lengthAtOffsetOut: nil,
                                        totalLengthOut: &length, dataPointerOut: &dataPointer)
            guard let ptr = dataPointer, length > 0 else { return }

            let float32Ptr = UnsafeRawPointer(ptr).bindMemory(
                to: Float.self, capacity: length / MemoryLayout<Float>.size
            )
            let sampleCount = length / MemoryLayout<Float>.size
            let ratio = 3  // 48000 / 16000

            var downsampled = [Float]()
            downsampled.reserveCapacity(sampleCount / ratio)
            for i in stride(from: 0, to: sampleCount, by: ratio) {
                downsampled.append(float32Ptr[i])
            }

            let chunk = downsampled.withUnsafeBytes { Data($0) }

            Task { @MainActor [weak self] in
                guard let self else { return }
                self.systemBuffer.append(chunk)
                if self.systemBuffer.count >= chunkBytes {
                    let sendData = Data(self.systemBuffer.prefix(chunkBytes))
                    self.systemBuffer.removeFirst(chunkBytes)
                    self.onAudioChunk?(sendData, "interviewer")
                }
            }
        }

        self.systemAudioHandler = outputHandler  // 保持强引用
        // 添加视频 handler（丢弃帧，防止 "stream output NOT found" 错误）
        let videoHandler = DiscardVideoHandler()
        self.videoHandler = videoHandler
        try stream.addStreamOutput(videoHandler, type: .screen,
                                   sampleHandlerQueue: DispatchQueue(label: "discard-video"))
        try stream.addStreamOutput(outputHandler, type: .audio,
                                   sampleHandlerQueue: DispatchQueue(label: "system-audio"))
        try await stream.startCapture()
    }

    private nonisolated func stopSystemAudioCapture() {
        Task { @MainActor [weak self] in
            try? await self?.scStream?.stopCapture()
            self?.scStream = nil
            self?.systemBuffer = Data()
        }
    }
}

// MARK: - SCStreamOutput

private class DiscardVideoHandler: NSObject, SCStreamOutput, @unchecked Sendable {
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of type: SCStreamOutputType) {
        // 丢弃视频帧，我们只需要音频
    }
}

private class SystemAudioOutputHandler: NSObject, SCStreamOutput, @unchecked Sendable {
    let handler: @Sendable (CMSampleBuffer) -> Void

    init(handler: @escaping @Sendable (CMSampleBuffer) -> Void) {
        self.handler = handler
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of type: SCStreamOutputType) {
        guard type == .audio else { return }
        handler(sampleBuffer)
    }
}
