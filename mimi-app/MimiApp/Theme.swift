import SwiftUI
import AppKit

/// iOS Dark Mode token palette. 镜像 Apple HIG 深色值，让三个浮窗在
/// NSVisualEffectView 磨砂玻璃之上读起来像通知中心 / 控制中心。
///
/// 旧调用站还在使用 `panelBackground` / `interviewerAccent` / `meAccent` /
/// `warningAccent` / `translationColor` / `textPrimary` 等名字 —— 名字保留，
/// 只换值，避免一次大规模 rename，迁移逐步进行。
enum Theme {

    // MARK: - 标签层级（iOS dark）
    static let labelPrimary    = Color.white
    static let labelSecondary  = Color.white.opacity(0.60)
    static let labelTertiary   = Color.white.opacity(0.30)
    static let labelQuaternary = Color.white.opacity(0.18)

    // 旧别名
    static let textPrimary   = labelPrimary
    static let textSecondary = labelSecondary
    static let textTertiary  = labelTertiary
    static let textMuted     = labelQuaternary

    // MARK: - 分割线 / 填充
    static let separator     = Color.white.opacity(0.10)
    static let fillPrimary   = Color.white.opacity(0.24)   // pressed
    static let fillSecondary = Color.white.opacity(0.18)   // active inactive but visible
    static let fillTertiary  = Color.white.opacity(0.12)   // resting tinted

    // MARK: - 系统色（iOS Dark 变体）
    static let systemBlue   = Color(red: 0x0A/255, green: 0x84/255, blue: 0xFF/255) // #0A84FF
    static let systemGreen  = Color(red: 0x30/255, green: 0xD1/255, blue: 0x58/255) // #30D158
    static let systemRed    = Color(red: 0xFF/255, green: 0x45/255, blue: 0x3A/255) // #FF453A
    static let systemOrange = Color(red: 0xFF/255, green: 0x9F/255, blue: 0x0A/255) // #FF9F0A
    static let systemGray   = Color(red: 0x8E/255, green: 0x8E/255, blue: 0x93/255) // #8E8E93

    // 旧别名
    static let interviewerAccent = systemBlue
    static let meAccent          = systemGreen
    static let warningAccent     = systemOrange
    static let translationColor  = labelSecondary

    // MARK: - 面板背景（磨砂层下面的 fallback / preview 用）
    /// `#1C1C1E` —— iOS systemGray6 dark；NSVisualEffectView 不可用时（preview）作底色
    static let panelBaseSolid = Color(red: 0x1C/255, green: 0x1C/255, blue: 0x1E/255)
    /// 真窗口里面板基色（半透明叠在磨砂层之上微调暗度）
    static let panelBackground = panelBaseSolid.opacity(0.55)
    /// 卡片 / banner 等略提升一层
    static let panelBackgroundElevated = Color.white.opacity(0.06)

    // MARK: - 圆角刻度（全部 .continuous，iOS squircle）
    enum Radius {
        static let chip:   CGFloat = 6
        static let button: CGFloat = 8
        static let card:   CGFloat = 12
        static let panel:  CGFloat = 16
    }

    // MARK: - 字号 / 字重
    static let headerFont = Font.system(size: 12, weight: .semibold)
    static let bodyFont   = Font.system(size: 13, weight: .regular)
    static let iconFont   = Font.system(size: 13, weight: .regular)
    static let chipFont   = Font.system(size: 11, weight: .semibold)
}
