cask "mimi" do
  version "0.1.0"
  sha256 "PASTE_FROM_release_sh_OUTPUT"

  url "https://github.com/marlonxie/MIMI/releases/download/v#{version}/MIMI-#{version}-arm64.zip"
  name "MIMI"
  desc "Real-time interview assistant for macOS (Mandarin <-> English/German)"
  homepage "https://github.com/marlonxie/MIMI"

  depends_on macos: ">= :sequoia"
  depends_on arch: :arm64
  # 自动装 ollama daemon（朋友机器零配置跑本地 LLM）
  depends_on formula: "ollama"

  # bundle 内部叫 MimiApp.app；装到 /Applications/MIMI.app 给用户看
  app "MimiApp.app", target: "MIMI.app"

  # 安装后跑：去 quarantine、起 ollama daemon、拉 Qwen3 模型、预热 mlx-whisper
  postflight do
    # MIMI 用 Apple Development 个人证书签名，没经过 Apple notarization；
    # macOS Gatekeeper 默认会弹 "无法验证" 警告。brew cask 装来的 app 我们
    # 主动剥 quarantine extended attribute 让首次启动不弹（朋友体验更顺）。
    # 永久解：申请 Apple Developer Program ($99/yr) + notarytool submit。
    ohai "Removing quarantine attribute"
    system_command "/usr/bin/xattr",
                   args: ["-dr", "com.apple.quarantine", "#{appdir}/MIMI.app"],
                   sudo: false,
                   print_stderr: false

    ohai "Starting Ollama daemon"
    system_command "/opt/homebrew/bin/brew",
                   args: ["services", "start", "ollama"],
                   sudo: false,
                   print_stderr: false
    sleep 3  # 等 daemon 起来再 pull

    ohai "Pulling Qwen3-4B-Instruct (~2.6GB) — first install only"
    system_command "/opt/homebrew/bin/ollama",
                   args: ["pull", "qwen3:4b-instruct-2507-q4_K_M"],
                   sudo: false

    ohai "Prefetching mlx-whisper small model (~500MB)"
    backend = staged_path/"MIMI.app/Contents/Resources/mimi-backend/mimi-backend"
    if backend.exist?
      system_command backend.to_s,
                     args: ["--prefetch-model"],
                     sudo: false,
                     timeout: 600  # 10 min 下载超时
    end
  end

  uninstall quit:    "com.marlon.MimiApp",
            signal: ["TERM", "com.marlon.MimiApp"]

  # `brew uninstall --zap mimi` 时清干净（包括 chroma_store / resources）
  zap trash: [
    "~/Library/Application Support/MIMI",
    "~/Library/Logs/MIMI",
    "~/Library/Preferences/com.marlon.MimiApp.plist",
    "~/Library/Saved Application State/com.marlon.MimiApp.savedState",
  ]
end
