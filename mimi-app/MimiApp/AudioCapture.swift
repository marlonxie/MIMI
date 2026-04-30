@preconcurrency import AVFoundation
import ScreenCaptureKit

@MainActor
@Observable
class AudioCaptureManager {
    var onAudioChunk: (@MainActor (Data, String) -> Void)?

    var isMicrophoneRunning: Bool { audioEngine?.isRunning ?? false }
    var isSystemAudioRunning: Bool { scStream != nil }

    private let targetSampleRate: Double = 16000
    // 1.0s 对应后端 LocalAgreement-2 流式 STT 的更新周期。
    // 改这个值时记得同步改 mimi-backend/config.yaml 的 audio.chunk_duration
    private let chunkDuration: Double = 1.0

    private var audioEngine: AVAudioEngine?
    /// engine 存活但 tap 是否已装。toggle off→on 时只 install tap + start，不重启 VP
    private var isMicTapInstalled = false
    private var micBuffer = Data()
    private var scStream: SCStream?
    private var systemBuffer = Data()
    private var systemAudioHandler: SystemAudioOutputHandler?  // 强引用，防止被释放
    private var videoHandler: DiscardVideoHandler?             // 强引用

    // MARK: - Microphone

    func startMicrophoneCapture() async throws {
        // 进程首次启动：申请权限 + 创建 engine + enable VP（VP 首次启用耗 1-3s）
        if audioEngine == nil {
            let granted = await withCheckedContinuation { continuation in
                AVAudioApplication.requestRecordPermission { granted in
                    continuation.resume(returning: granted)
                }
            }
            guard granted else {
                print("麦克风权限被拒绝")
                return
            }

            let engine = AVAudioEngine()
            let inputNode = engine.inputNode

            // 启用 Apple 原生 VoiceProcessingIO：AEC + NS + AGC，硬件加速。
            // 实测和 ScreenCaptureKit 可共存（老 commit 13f1c3d 的"互斥"结论已被推翻）。
            // Ducking 级别设为 .min（与 FaceTime/Zoom 一致的 VoIP 标准行为）。
            do {
                try inputNode.setVoiceProcessingEnabled(true)
                if #available(macOS 14.0, *) {
                    inputNode.voiceProcessingOtherAudioDuckingConfiguration =
                        AVAudioVoiceProcessingOtherAudioDuckingConfiguration(
                            enableAdvancedDucking: false,
                            duckingLevel: .min
                        )
                }
            } catch {
                print("Voice processing not available: \(error)")
            }

            audioEngine = engine
        }

        guard let engine = audioEngine else { return }
        let inputNode = engine.inputNode

        // 第二次起复用 engine：只 install tap + start，跳过 VP 重启避免 1-3s 卡顿
        if !isMicTapInstalled {
            let inputFormat = inputNode.outputFormat(forBus: 0)

            guard let targetFormat = AVAudioFormat(
                commonFormat: .pcmFormatFloat32,
                sampleRate: targetSampleRate,
                channels: 1,
                interleaved: false
            ) else { return }

            let converter = AVAudioConverter(from: inputFormat, to: targetFormat)
            // VP 启用后 inputFormat 会报告多通道数（实测 9，也有人见过 3 / 7，硬件相关）。
            // channel 0 是真实 mic，其他是 VP 内部通道（reference / echo estimate 等）。
            // 必须显式 channelMap = [0]，否则非标准布局下 converter mix-down 会输出静音。
            converter?.channelMap = [0]
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
            isMicTapInstalled = true
        }

        if !engine.isRunning {
            try engine.start()
        }
    }

    func stopMicrophoneCapture() {
        // 不释放 engine，下次 toggle 复用避免 VP 重启
        if isMicTapInstalled {
            audioEngine?.inputNode.removeTap(onBus: 0)
            isMicTapInstalled = false
        }
        audioEngine?.stop()
        micBuffer = Data()
    }

    // MARK: - System Audio

    func startSystemAudioCapture() async throws {
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

    nonisolated func stopSystemAudioCapture() {
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
