#!/usr/bin/env bash
# release.sh — 一键打包 MIMI 发给用户
#
#   ./scripts/release.sh 0.2.0           # 出 zip + dmg 但不上传
#   ./scripts/release.sh 0.2.0 --publish # 同上 + gh release create
#
# 步骤：
#   1) PyInstaller backend → mimi-backend/dist/mimi-backend/ (~1GB，含 sentence_transformers)
#   2) xcodebuild Release MimiApp.app (含 backend + bundled ollama，~1.5GB)
#   3) zip → dist/MIMI-<version>-arm64.zip      （兼容 brew cask 路径）
#   4) dmg → dist/MIMI-<version>.dmg            （朋友双击装路径，推荐）
#   5) manifest → dist/MIMI-<version>.manifest.txt
#   6) （可选）gh release create 上传 zip + dmg + manifest
#
# 用户机器最终二选一：
#   - DMG（推荐，零命令行）：双击 .dmg → 拖 MIMI 到 Applications → 右键打开
#   - Cask（命令行）：brew tap marlonxie/mimi && brew install --cask mimi
set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    echo "usage: $0 <version>   (e.g. $0 0.1.0)"
    exit 1
fi

PUBLISH=0
if [[ "${2:-}" == "--publish" ]]; then
    PUBLISH=1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="/Users/marlon/anaconda3/envs/mimi/bin/python"

echo "===== [1/4] PyInstaller backend ====="
cd "$ROOT/mimi-backend"
# --clean 让 spec 里 datas 包含的 config.yaml 用 dev 版本（port 8765 一致）
"$PY" -m PyInstaller mimi-backend.spec --clean -y > /tmp/mimi-pyinstaller.log 2>&1 || {
    echo "PyInstaller failed — see /tmp/mimi-pyinstaller.log"
    tail -30 /tmp/mimi-pyinstaller.log
    exit 1
}
echo "backend → $ROOT/mimi-backend/dist/mimi-backend ($(du -sh "$ROOT/mimi-backend/dist/mimi-backend" | awk '{print $1}'))"

echo "===== [2/4] xcodebuild Release ====="
cd "$ROOT/mimi-app"
BUILD_DIR="$ROOT/mimi-app/build"
rm -rf "$BUILD_DIR"
xcodebuild -project MimiApp.xcodeproj -scheme MimiApp \
    -configuration Release -destination 'platform=macOS' \
    -derivedDataPath "$BUILD_DIR" build > /tmp/mimi-xcodebuild.log 2>&1 || {
    echo "xcodebuild failed — see /tmp/mimi-xcodebuild.log"
    tail -30 /tmp/mimi-xcodebuild.log
    exit 1
}

APP="$BUILD_DIR/Build/Products/Release/MimiApp.app"
[[ -d "$APP" ]] || { echo "MimiApp.app not at $APP"; exit 1; }
echo "app → $APP ($(du -sh "$APP" | awk '{print $1}'))"

echo "===== [3/5] zip + shasum ====="
mkdir -p "$ROOT/dist"
ZIP_NAME="MIMI-$VERSION-arm64.zip"
ZIP_PATH="$ROOT/dist/$ZIP_NAME"
rm -f "$ZIP_PATH"
cd "$(dirname "$APP")"
# ditto 保留 codesign / extended attributes，比 zip 命令更靠谱
ditto -c -k --sequesterRsrc --keepParent "MimiApp.app" "$ZIP_PATH"
ZIP_SHA="$(shasum -a 256 "$ZIP_PATH" | awk '{print $1}')"
ZIP_SIZE_MB="$(du -m "$ZIP_PATH" | awk '{print $1}')"
echo "zip → $ZIP_PATH (${ZIP_SIZE_MB}MB)"
echo "zip sha256: $ZIP_SHA"

echo "===== [4/5] create-dmg ====="
if ! command -v create-dmg >/dev/null 2>&1; then
    echo "warning: create-dmg not installed → brew install create-dmg"
    brew install create-dmg
fi

DMG_NAME="MIMI-$VERSION.dmg"
DMG_PATH="$ROOT/dist/$DMG_NAME"
DMG_STAGING="$ROOT/dist/dmg-staging"

rm -rf "$DMG_STAGING" "$DMG_PATH"
mkdir -p "$DMG_STAGING"
# 用 MIMI.app 作为可见名（cask 也是 rename 成 MIMI.app）
ditto "$APP" "$DMG_STAGING/MIMI.app"

# create-dmg 偶尔在 macOS 26 上 exit 2 但 dmg 已生成；用 || true 保守
create-dmg \
    --volname "MIMI" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon-size 100 \
    --icon "MIMI.app" 150 200 \
    --hide-extension "MIMI.app" \
    --app-drop-link 450 200 \
    --format UDZO \
    --no-internet-enable \
    "$DMG_PATH" \
    "$DMG_STAGING/" || true

if [[ ! -f "$DMG_PATH" ]]; then
    echo "error: DMG creation failed"
    exit 1
fi

DMG_SHA="$(shasum -a 256 "$DMG_PATH" | awk '{print $1}')"
DMG_SIZE_MB="$(du -m "$DMG_PATH" | awk '{print $1}')"
echo "dmg → $DMG_PATH (${DMG_SIZE_MB}MB)"
echo "dmg sha256: $DMG_SHA"

# 清 staging（dmg 已经包好了）
rm -rf "$DMG_STAGING"

echo "===== [5/5] manifest ====="
MANIFEST="$ROOT/dist/MIMI-$VERSION.manifest.txt"
cat > "$MANIFEST" <<EOF
version: $VERSION
arch: arm64
built_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)

# Direct DMG (drag-to-install, recommended for casual users)
dmg: $DMG_NAME
dmg_sha256: $DMG_SHA
dmg_size_mb: $DMG_SIZE_MB

# ZIP (for Homebrew cask path)
zip: $ZIP_NAME
zip_sha256: $ZIP_SHA
zip_size_mb: $ZIP_SIZE_MB
EOF
cat "$MANIFEST"

if [[ "$PUBLISH" -eq 1 ]]; then
    echo "===== [+] gh release create v$VERSION ====="
    cd "$ROOT"
    gh release create "v$VERSION" "$DMG_PATH" "$ZIP_PATH" "$MANIFEST" \
        --title "v$VERSION" \
        --notes "MIMI v$VERSION

**For most users (recommended)**: download \`$DMG_NAME\` → double-click → drag MIMI to Applications.

**For Homebrew users**: \`brew tap marlonxie/mimi && brew install --cask mimi\` (uses \`$ZIP_NAME\`).

sha256 (dmg): \`$DMG_SHA\`
sha256 (zip): \`$ZIP_SHA\`"
    echo "released → https://github.com/marlonxie/MIMI/releases/tag/v$VERSION"
    echo ""
    echo "===== next: update homebrew-mimi/Casks/mimi.rb ====="
    echo "  version \"$VERSION\""
    echo "  sha256 \"$ZIP_SHA\"   ← zip sha256 (cask uses zip)"
else
    echo ""
    echo "(skipped gh release — re-run with '$0 $VERSION --publish' to upload)"
fi
