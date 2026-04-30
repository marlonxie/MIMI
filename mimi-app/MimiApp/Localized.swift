import Foundation

/// 界面语言（仅前端 UI 字符串本地化；不影响面试 / 母语翻译设置）。
enum UILang: String, CaseIterable {
    case zh, en, de

    var displayName: String {
        switch self {
        case .zh: return "中文"
        case .en: return "English"
        case .de: return "Deutsch"
        }
    }
}

/// 翻译表。Key 用扁平化命名（域.功能），值是 [lang: text] 字典。
/// Key 不存在时 fallback 返回 key 本身（开发时立即可见缺译）。
enum L {
    static let strings: [String: [UILang: String]] = [
        // MARK: Hub tooltips
        "hub.mic":          [.zh: "麦克风",          .en: "Microphone",        .de: "Mikrofon"],
        "hub.systemAudio":  [.zh: "屏幕音频",        .en: "System Audio",      .de: "System-Audio"],
        "hub.captions":     [.zh: "字幕窗",          .en: "Captions Window",   .de: "Untertitel-Fenster"],
        "hub.suggestion":   [.zh: "回答提示窗",      .en: "Suggestion Window", .de: "Vorschlag-Fenster"],
        "hub.upload":       [.zh: "上传 RAG 资料",   .en: "Upload RAG Files",  .de: "RAG-Dateien hochladen"],
        "hub.settings":     [.zh: "设置",            .en: "Settings",          .de: "Einstellungen"],
        "hub.minimize":     [.zh: "最小化",          .en: "Minimize",          .de: "Minimieren"],
        "hub.quit":         [.zh: "退出",            .en: "Quit",              .de: "Beenden"],

        // MARK: Captions
        "captions.header":          [.zh: "翻译",         .en: "Translation",   .de: "Übersetzung"],
        "captions.count":           [.zh: "%d 条",        .en: "%d entries",    .de: "%d Einträge"],
        "captions.speaker.interviewer": [.zh: "面试官",   .en: "Interviewer",   .de: "Interviewer"],
        "captions.speaker.me":          [.zh: "我",       .en: "Me",            .de: "Ich"],
        "captions.suggestion.tip":  [.zh: "为这句生成回答建议",
                                     .en: "Generate suggestion for this sentence",
                                     .de: "Vorschlag für diesen Satz generieren"],

        // MARK: Suggestion
        "suggestion.header":        [.zh: "回答提示",     .en: "Suggestion",    .de: "Vorschlag"],
        "suggestion.thinking":      [.zh: "思考中…",      .en: "Thinking…",     .de: "Denkt nach…"],
        "suggestion.section.understanding": [.zh: "理解", .en: "Understanding", .de: "Verständnis"],
        "suggestion.section.keyPoints":     [.zh: "要点", .en: "Key Points",    .de: "Stichpunkte"],
        "suggestion.section.sampleAnswer":  [.zh: "示例回答",
                                             .en: "Sample Answer",
                                             .de: "Beispielantwort"],
        "suggestion.placeholder":   [.zh: "点击面试官字幕行 → 点击 💡 生成建议；或等待自动触发…",
                                     .en: "Click an interviewer line → tap 💡 to suggest; or wait for auto-trigger…",
                                     .de: "Auf eine Zeile des Interviewers klicken → 💡 antippen für Vorschlag; oder auf automatische Auslösung warten…"],

        // MARK: API key banner
        "apiKey.banner.title":      [.zh: "%@需配置 API key",
                                     .en: "API key required to %@",
                                     .de: "API-Schlüssel benötigt für %@"],
        "apiKey.banner.subtitle":   [.zh: "打开 Settings (Cmd+,) → API",
                                     .en: "Open Settings (⌘,) → API",
                                     .de: "Einstellungen öffnen (⌘,) → API"],
        "apiKey.reason.translation": [.zh: "启用翻译",
                                      .en: "enable translation",
                                      .de: "Übersetzung aktivieren"],
        "apiKey.reason.rag":        [.zh: "启用 AI 回答提示",
                                     .en: "enable AI suggestions",
                                     .de: "KI-Vorschläge aktivieren"],

        // MARK: Menu bar
        "menu.show":            [.zh: "显示悬浮窗",   .en: "Show Panels",   .de: "Panels einblenden"],
        "menu.hide":            [.zh: "隐藏悬浮窗",   .en: "Hide Panels",   .de: "Panels ausblenden"],
        "menu.connected":       [.zh: "后端已连接",   .en: "Backend connected",
                                                                          .de: "Backend verbunden"],
        "menu.disconnected":    [.zh: "后端未连接",   .en: "Backend offline",
                                                                          .de: "Backend offline"],
        "menu.export":          [.zh: "导出对话记录", .en: "Export Transcript",
                                                                          .de: "Verlauf exportieren"],
        "menu.settings":        [.zh: "设置…",        .en: "Settings…",     .de: "Einstellungen…"],
        "menu.quit":            [.zh: "退出",         .en: "Quit",          .de: "Beenden"],

        // MARK: Settings
        "settings.tab.language":    [.zh: "语言",     .en: "Language",      .de: "Sprache"],
        "settings.tab.suggestion":  [.zh: "提示",     .en: "Suggestion",    .de: "Vorschlag"],
        "settings.tab.api":         [.zh: "API",      .en: "API",           .de: "API"],
        "settings.tab.ui":          [.zh: "界面",     .en: "Interface",     .de: "Oberfläche"],
        "settings.uiLanguage":      [.zh: "界面语言", .en: "Interface Language",
                                                                          .de: "Oberflächensprache"],
        "settings.uiLanguage.hint": [.zh: "切换界面文字（不影响识别 / 翻译语言）",
                                     .en: "Switch UI text (does not affect recognition / translation languages)",
                                     .de: "UI-Text wechseln (beeinflusst Erkennung / Übersetzung nicht)"],
        "settings.interviewLanguage": [.zh: "面试语言", .en: "Interview Language",
                                                                          .de: "Interview-Sprache"],
        "settings.nativeLanguage":  [.zh: "我的母语", .en: "My Native Language",
                                                                          .de: "Meine Muttersprache"],
        "settings.languageHint":    [.zh: "切换会立即推送到后端，无需重启录音。",
                                     .en: "Changes take effect immediately; no need to restart recording.",
                                     .de: "Änderungen werden sofort wirksam; kein Neustart nötig."],
        "settings.suggestion.toggle": [.zh: "启用 RAG 面试提示",
                                       .en: "Enable RAG Interview Suggestions",
                                       .de: "RAG-Vorschläge aktivieren"],
        "settings.suggestion.hint": [.zh: "开启后，面试官说完一句 ~3s 会基于你上传的资料自动给出回答参考。",
                                     .en: "When enabled, ~3s after the interviewer finishes a sentence, the app auto-suggests answers based on your uploaded materials.",
                                     .de: "Wenn aktiviert, schlägt die App ~3s nach dem Sprechen des Interviewers automatisch Antworten basierend auf hochgeladenen Materialien vor."],
        "settings.api.provider":    [.zh: "LLM Provider", .en: "LLM Provider",
                                                                          .de: "LLM-Anbieter"],
        "settings.api.local":       [.zh: "本地模型（即将支持）",
                                     .en: "Local model (coming soon)",
                                     .de: "Lokales Modell (bald verfügbar)"],
        "settings.api.placeholder": [.zh: "粘贴你的 API key",
                                     .en: "Paste your API key",
                                     .de: "API-Schlüssel einfügen"],
        "settings.api.save":        [.zh: "保存并应用", .en: "Save & Apply",
                                                                          .de: "Speichern & Anwenden"],
        "settings.api.translationReady": [.zh: "翻译已就绪",
                                          .en: "Translation ready",
                                          .de: "Übersetzung bereit"],
        "settings.api.envHint":     [.zh: "后端已通过 .env 配置就绪。在此输入会覆盖 .env 的 key。",
                                     .en: "Backend is configured via .env. Entering a key here overrides .env.",
                                     .de: "Backend ist über .env konfiguriert. Hier eingegebener Schlüssel überschreibt .env."],
        "settings.api.keychainHint": [.zh: "Key 仅存 macOS Keychain，本地保存，不上传。",
                                      .en: "Key is stored only in macOS Keychain — local-only, never uploaded.",
                                      .de: "Schlüssel wird nur im macOS-Schlüsselbund lokal gespeichert, nie hochgeladen."],

        // MARK: Upload alert
        "upload.title":             [.zh: "选择简历 / 项目说明文件",
                                     .en: "Choose résumé / project files",
                                     .de: "Lebenslauf / Projektdateien wählen"],
        "upload.alert.message":     [.zh: "已复制 %d 个文件到 resources/",
                                     .en: "Copied %d file(s) to resources/",
                                     .de: "%d Datei(en) nach resources/ kopiert"],
        "upload.alert.info":        [.zh: "请运行：\ncd mimi-backend && python -m rag.indexer\n重建索引后回答提示功能才会用到新资料。",
                                     .en: "Please run:\ncd mimi-backend && python -m rag.indexer\nto rebuild the index. New materials only take effect after that.",
                                     .de: "Bitte ausführen:\ncd mimi-backend && python -m rag.indexer\nIndex muss neu erstellt werden, sonst werden neue Materialien nicht genutzt."],
    ]

    static func t(_ key: String, lang: UILang) -> String {
        strings[key]?[lang] ?? key
    }
}
