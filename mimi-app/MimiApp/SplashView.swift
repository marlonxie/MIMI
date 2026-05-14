import SwiftUI

/// 启动加载页 — 双击 app 后立刻出现，遮罩到后端 lifecycle=ready。
///
/// 三态：
/// - WS 未连上 / `lifecycle == .warming`：转圈 + "正在准备 MIMI..."
/// - `isPullingModel`（首次启动拉 Qwen3）：进度条 + 字节数
/// - `lifecycle == .ready`：immediately 由 AppDelegate 关闭 splash（不会停在 ready 状态）
///
/// 关闭逻辑：AppDelegate 监听 `appState.isAppReady` 切换为 true → 关 splash → 接 onboarding/主界面
struct SplashView: View {
    @Bindable var appState: AppState

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            if appState.isPullingModel {
                pullingView
            } else {
                warmingView
            }

            Spacer()
        }
        .frame(width: 420, height: 280)
        .padding()
    }

    // MARK: warming（默认状态：转圈 + 文案）

    private var warmingView: some View {
        VStack(spacing: 16) {
            Image(systemName: "sparkles")
                .font(.system(size: 56))
                .foregroundStyle(.tint)
                .symbolEffect(.pulse)

            ProgressView()
                .scaleEffect(0.8)

            Text("正在准备 MIMI…")
                .font(.headline)

            Text(appState.wsClient.isConnected
                 ? "加载本地 AI 模型，约需 8 秒"
                 : "等待后端启动…")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    // MARK: pulling（首次启动 Qwen3 下载）

    private var pullingView: some View {
        // 取第一个还没完成的模型来展示（通常只有一个 — qwen3）
        let pending = appState.modelProgress
            .first { !$0.value.isReady }

        return VStack(spacing: 14) {
            Image(systemName: "shippingbox.fill")
                .font(.system(size: 56))
                .foregroundStyle(.tint)
                .symbolEffect(.pulse)

            Text("首次启动：下载本地 AI 模型")
                .font(.headline)

            if let entry = pending {
                ProgressView(value: Double(entry.value.completed),
                             total: Double(max(entry.value.total, 1)))
                    .progressViewStyle(.linear)
                    .frame(width: 320)

                Text("\(formatBytes(entry.value.completed)) / \(formatBytes(entry.value.total))")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
            } else {
                ProgressView().scaleEffect(0.8)
            }

            Text("仅首次启动 — 约 10–20 分钟，请保持联网")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }

    private func formatBytes(_ bytes: Int64) -> String {
        let mb = Double(bytes) / 1024 / 1024
        if mb < 1024 { return String(format: "%.0f MB", mb) }
        return String(format: "%.2f GB", mb / 1024)
    }
}
