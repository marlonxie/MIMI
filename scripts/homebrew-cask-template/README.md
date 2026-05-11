# Homebrew Tap Setup

This is a **template**. Brew tap needs to live in a separate GitHub repo named exactly `homebrew-mimi` (the `homebrew-` prefix is required by Homebrew convention).

## One-time setup

1. **Create the tap repo on GitHub**: `marlonxie/homebrew-mimi` (public, empty).

2. **Clone & seed it**:
   ```bash
   git clone git@github.com:marlonxie/homebrew-mimi.git ~/homebrew-mimi
   mkdir -p ~/homebrew-mimi/Casks
   cp /Users/marlon/MIMI/scripts/homebrew-cask-template/mimi.rb ~/homebrew-mimi/Casks/
   cd ~/homebrew-mimi
   git add Casks/mimi.rb
   git commit -m "feat: initial mimi cask"
   git push origin main
   ```

## Release a new version

```bash
# 1. Build + zip + publish GitHub release on MIMI repo
cd /Users/marlon/MIMI
./scripts/release.sh 0.1.0 --publish
# 输出会显示 sha256 和 version

# 2. 更新 cask 里的 version + sha256
cd ~/homebrew-mimi/Casks
# 编辑 mimi.rb 把 version 和 sha256 改成 release.sh 输出的值
git commit -am "bump to v0.1.0"
git push
```

## 朋友机器一行命令安装

```bash
brew tap marlonxie/mimi
brew install --cask mimi
# postflight 自动：起 ollama daemon、拉 Qwen3 模型、预下 mlx-whisper
open -a MIMI
```

## 卸载（连数据一起清）

```bash
brew uninstall --zap --cask mimi
```

`--zap` 删 `~/Library/Application Support/MIMI` / `~/Library/Logs/MIMI` / `~/Library/Preferences/com.marlon.MimiApp.plist`。

Ollama daemon + Qwen3 模型不会自动卸（因为是 `depends_on cask`，可能被其他东西用）。要清：
```bash
brew uninstall --cask ollama
rm -rf ~/.ollama
```
