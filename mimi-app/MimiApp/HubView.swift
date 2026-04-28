import SwiftUI
import AppKit

/// Hub palette：常用按钮聚集地。纯图标，常态无底色，激活态才有圆角填充。
/// 布局（左→右）：[关闭][最小化] | [mic][speaker] | [字幕][回答] | [上传][设置]
struct HubView: View {
    @Bindable var appState: AppState
    let appDelegate: AppDelegate
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        HStack(spacing: 4) {
            HubButton(icon: "xmark", tone: .danger, active: false, tooltip: "退出") {
                NSApp.terminate(nil)
            }
            HubButton(icon: "minus", tone: .neutral, active: false, tooltip: "最小化") {
                appDelegate.minimizeAll()
            }

            HubDivider()

            HubButton(
                icon: appState.isMicrophoneEnabled ? "mic.fill" : "mic.slash.fill",
                tone: .accent,
                active: appState.isMicrophoneEnabled,
                tooltip: "麦克风"
            ) { Task { await appState.toggleMicrophone() } }

            HubButton(
                icon: appState.isSystemAudioEnabled ? "speaker.wave.2.fill" : "speaker.slash.fill",
                tone: .accent,
                active: appState.isSystemAudioEnabled,
                tooltip: "屏幕音频"
            ) { Task { await appState.toggleSystemAudio() } }

            HubDivider()

            HubButton(
                icon: "translate",
                tone: .accent,
                active: appState.captionsVisible,
                tooltip: "字幕窗"
            ) { appState.captionsVisible.toggle() }

            HubButton(
                icon: "sparkles",
                tone: .accent,
                active: appState.suggestionVisible,
                tooltip: "回答提示窗"
            ) { appState.suggestionVisible.toggle() }

            HubDivider()

            HubButton(icon: "square.and.arrow.up", tone: .accent, active: false, tooltip: "上传 RAG 资料") {
                appDelegate.pickRagResources()
            }

            HubButton(icon: "gearshape.fill", tone: .accent, active: false, tooltip: "设置") {
                NSApp.activate(ignoringOtherApps: true)
                openSettings()
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(Theme.panelBackground)
    }
}

// MARK: - Hub button primitives

private enum HubTone {
    case accent      // 蓝：常用功能
    case neutral     // 白：弱化操作
    case danger      // 红：关闭
}

private struct HubButton: View {
    let icon: String
    let tone: HubTone
    let active: Bool
    let tooltip: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(foreground)
                .frame(width: 30, height: 26)
                .background(background)
                .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
        }
        .buttonStyle(.plain)
        .help(tooltip)
    }

    private var foreground: Color {
        switch (tone, active) {
        case (.accent, true):   return .white
        case (.accent, false):  return Theme.interviewerAccent
        case (.neutral, _):     return Theme.textPrimary
        case (.danger, _):      return Color(red: 1.0, green: 0.45, blue: 0.45)
        }
    }

    /// 仅 active 状态有底色；常态完全透明（"按钮没点击的时候不要有边框"）
    private var background: Color {
        guard active else { return .clear }
        switch tone {
        case .accent:  return Theme.interviewerAccent.opacity(0.85)
        case .neutral: return Color.white.opacity(0.10)
        case .danger:  return Color(red: 0.85, green: 0.30, blue: 0.30)
        }
    }
}

private struct HubDivider: View {
    var body: some View {
        Rectangle()
            .fill(Color.white.opacity(0.10))
            .frame(width: 1, height: 16)
            .padding(.horizontal, 2)
    }
}

#Preview("hub - 全关") {
    HubView(appState: AppState(), appDelegate: AppDelegate())
        .frame(width: 320, height: 40)
}

#Preview("hub - 字幕开 + 麦克风开") {
    let s: AppState = {
        let s = AppState()
        s.isMicrophoneEnabled = true
        s.isSystemAudioEnabled = false
        s.captionsVisible = true
        s.suggestionVisible = false
        return s
    }()
    HubView(appState: s, appDelegate: AppDelegate())
        .frame(width: 320, height: 40)
}
