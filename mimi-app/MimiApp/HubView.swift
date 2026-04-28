import SwiftUI
import AppKit

/// Hub palette：常用按钮聚集地。横排一行，作为主控面板的内容。
struct HubView: View {
    @Bindable var appState: AppState
    let appDelegate: AppDelegate
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        HStack(spacing: 12) {
            // 麦克风
            Button { Task { await appState.toggleMicrophone() } } label: {
                Image(systemName: appState.isMicrophoneEnabled ? "mic.fill" : "mic.slash.fill")
                    .foregroundStyle(appState.isMicrophoneEnabled ? Theme.textPrimary : .red)
                    .frame(width: 18, height: 18)
            }.buttonStyle(.plain).help("麦克风")

            // 屏幕音频
            Button { Task { await appState.toggleSystemAudio() } } label: {
                Image(systemName: appState.isSystemAudioEnabled ? "speaker.wave.2.fill" : "speaker.slash.fill")
                    .foregroundStyle(appState.isSystemAudioEnabled ? Theme.textPrimary : .red)
                    .frame(width: 18, height: 18)
            }.buttonStyle(.plain).help("屏幕音频")

            Divider().frame(height: 14)

            // 录音主开关
            Button {
                if appState.isCapturing {
                    appState.stopCapture()
                } else {
                    Task { await appState.startCapture() }
                }
            } label: {
                Image(systemName: appState.isCapturing ? "stop.circle.fill" : "record.circle")
                    .foregroundStyle(appState.isCapturing ? .red : Theme.interviewerAccent)
                    .frame(width: 18, height: 18)
            }.buttonStyle(.plain).help(appState.isCapturing ? "停止录音" : "开始录音")

            Text(statusText)
                .font(.caption)
                .foregroundStyle(Theme.textSecondary)

            Spacer()

            // 子窗显示开关
            Toggle("字幕", isOn: $appState.captionsVisible)
                .toggleStyle(.button)
                .controlSize(.small)
            Toggle("回答", isOn: $appState.suggestionVisible)
                .toggleStyle(.button)
                .controlSize(.small)

            Divider().frame(height: 14)

            // 上传 RAG 资料
            Button { appDelegate.pickRagResources() } label: {
                Image(systemName: "tray.and.arrow.down")
                    .foregroundStyle(Theme.textPrimary)
                    .frame(width: 18, height: 18)
            }.buttonStyle(.plain).help("上传 RAG 资料")

            // 设置
            Button {
                NSApp.activate(ignoringOtherApps: true)
                openSettings()
            } label: {
                Image(systemName: "gearshape")
                    .foregroundStyle(Theme.textPrimary)
                    .frame(width: 18, height: 18)
            }.buttonStyle(.plain).help("设置")

            // 最小化（== 菜单栏"隐藏悬浮窗"）
            Button { appDelegate.minimizeAll() } label: {
                Image(systemName: "minus.circle")
                    .foregroundStyle(.yellow)
                    .frame(width: 18, height: 18)
            }.buttonStyle(.plain).help("最小化")

            // 关闭 == 退出 app
            Button { NSApp.terminate(nil) } label: {
                Image(systemName: "xmark.circle")
                    .foregroundStyle(.red)
                    .frame(width: 18, height: 18)
            }.buttonStyle(.plain).help("退出")
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Theme.panelBackground)
    }

    private var statusText: String {
        if !appState.isCapturing { return "未录音" }
        switch (appState.isMicrophoneEnabled, appState.isSystemAudioEnabled) {
        case (true, true):   return "双路录音"
        case (true, false):  return "仅麦克风"
        case (false, true):  return "仅屏幕"
        case (false, false): return "静音"
        }
    }
}
