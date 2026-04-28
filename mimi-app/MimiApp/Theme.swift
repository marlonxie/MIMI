import SwiftUI

/// 集中配色常量。改色只动这里。
///
/// 设计原则：
/// - 冷色基调：背景蓝灰 tint > 纯黑，accent 用柔和色不用饱和原色
/// - 文字层级 opacity 差 ~25%（避免"全是 0.5/0.9 二极管"）
/// - 翻译用偏冷蓝灰让它"沉下去"，字幕原文"浮上来"，避免黄+白同行视觉竞争
enum Theme {
    // MARK: - 背景

    /// Panel 主背景：深灰偏冷，略带蓝 tint，半透明
    static let panelBackground = Color(red: 0.08, green: 0.10, blue: 0.13, opacity: 0.78)

    /// 提升一层（card / banner 用）
    static let panelBackgroundElevated = Color(red: 0.12, green: 0.14, blue: 0.18, opacity: 0.85)

    // MARK: - 文字层级

    /// 主文字：已 final 的字幕、关键内容
    static let textPrimary = Color.white.opacity(0.95)

    /// 次要文字：翻译、二级信息
    static let textSecondary = Color.white.opacity(0.65)

    /// 三级文字：tentative 候选、placeholder
    static let textTertiary = Color.white.opacity(0.40)

    /// 辅助文字：时间戳、注释
    static let textMuted = Color.white.opacity(0.28)

    // MARK: - Accent

    /// 面试官标签：柔和天蓝
    static let interviewerAccent = Color(red: 0.50, green: 0.78, blue: 0.95)

    /// 我的标签：柔和浅绿
    static let meAccent = Color(red: 0.55, green: 0.85, blue: 0.65)

    /// 警告 / API key 提示：柔和橙
    static let warningAccent = Color(red: 1.00, green: 0.65, blue: 0.30)

    // MARK: - 翻译

    /// 翻译色：冷调浅蓝灰，比黄色低饱和不抢字幕视觉
    static let translationColor = Color(red: 0.78, green: 0.86, blue: 0.94, opacity: 0.85)
}
