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
            HubButton(icon: "xmark", tone: .danger, active: false,
                      tooltip: appState.t("hub.quit")) {
                NSApp.terminate(nil)
            }
            HubButton(icon: "minus", tone: .neutral, active: false,
                      tooltip: appState.t("hub.minimize")) {
                appDelegate.minimizeAll()
            }

            HubDivider()

            HubButton(
                icon: appState.isMicrophoneEnabled ? "mic.fill" : "mic.slash.fill",
                tone: .accent,
                active: appState.isMicrophoneEnabled,
                tooltip: appState.t("hub.mic")
            ) { Task { await appState.toggleMicrophone() } }

            HubButton(
                icon: appState.isSystemAudioEnabled ? "speaker.wave.2.fill" : "speaker.slash.fill",
                tone: .accent,
                active: appState.isSystemAudioEnabled,
                tooltip: appState.t("hub.systemAudio")
            ) { Task { await appState.toggleSystemAudio() } }

            HubDivider()

            HubButton(
                icon: "translate",
                tone: .accent,
                active: appState.captionsVisible,
                tooltip: appState.t("hub.captions")
            ) { appState.captionsVisible.toggle() }

            HubButton(
                icon: "sparkles",
                tone: .accent,
                active: appState.suggestionVisible,
                tooltip: appState.t("hub.suggestion")
            ) { appState.suggestionVisible.toggle() }

            HubDivider()

            HubButton(icon: "square.and.arrow.up", tone: .accent, active: false,
                      tooltip: appState.t("hub.upload")) {
                appDelegate.pickRagResources()
            }

            HubButton(icon: "gearshape.fill", tone: .accent, active: false,
                      tooltip: appState.t("hub.settings")) {
                NSApp.activate(ignoringOtherApps: true)
                openSettings()
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
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
                .font(.system(size: 14, weight: .regular))   // iOS Symbol 默认更轻
                .foregroundStyle(foreground)
                .frame(width: 32, height: 28)
                .background(background)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.button,
                                            style: .continuous))
        }
        .buttonStyle(.plain)
        .help(tooltip)
    }

    private var foreground: Color {
        switch (tone, active) {
        case (.accent, true):   return .white
        case (.accent, false):  return Theme.labelSecondary
        case (.neutral, _):     return Theme.labelSecondary
        case (.danger, _):      return Theme.systemRed
        }
    }

    /// 仅 active 才有底色；inactive 透明（"未点击无边框"）
    private var background: Color {
        guard active else { return .clear }
        switch tone {
        case .accent:  return Theme.systemBlue
        case .neutral: return Theme.fillSecondary
        case .danger:  return Theme.systemRed.opacity(0.85)
        }
    }
}

private struct HubDivider: View {
    var body: some View {
        Rectangle()
            .fill(Theme.separator)
            .frame(width: 1, height: 18)
            .padding(.horizontal, 2)
    }
}

#Preview("hub - 全关") {
    ZStack {
        Theme.panelBaseSolid
        HubView(appState: AppState(), appDelegate: AppDelegate())
    }
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
    ZStack {
        Theme.panelBaseSolid
        HubView(appState: s, appDelegate: AppDelegate())
    }
    .frame(width: 320, height: 40)
}
