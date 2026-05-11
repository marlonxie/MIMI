#!/usr/bin/env bash
# release.sh — 一键打包 MIMI 发给朋友
#
#   ./scripts/release.sh 0.1.0
#
# 步骤：
#   1) PyInstaller backend → mimi-backend/dist/mimi-backend/ (607MB)
#   2) xcodebuild Release MimiApp.app (含 backend，~650MB)
#   3) zip → dist/MIMI-<version>-arm64.zip
#   4) shasum → 用于 homebrew-mimi/Casks/mimi.rb
#   5) （可选）gh release create —— 加 --publish 才执行
#
# 朋友机器最终用：
#   brew tap marlonxie/mimi && brew install --cask mimi
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

echo "===== [3/4] zip + shasum ====="
mkdir -p "$ROOT/dist"
ZIP_NAME="MIMI-$VERSION-arm64.zip"
ZIP_PATH="$ROOT/dist/$ZIP_NAME"
rm -f "$ZIP_PATH"
cd "$(dirname "$APP")"
# ditto 保留 codesign / extended attributes，比 zip 命令更靠谱
ditto -c -k --sequesterRsrc --keepParent "MimiApp.app" "$ZIP_PATH"
SHA="$(shasum -a 256 "$ZIP_PATH" | awk '{print $1}')"
SIZE_MB="$(du -m "$ZIP_PATH" | awk '{print $1}')"
echo "zip → $ZIP_PATH (${SIZE_MB}MB)"
echo "sha256: $SHA"

echo "===== [4/4] manifest ====="
MANIFEST="$ROOT/dist/MIMI-$VERSION.manifest.txt"
cat > "$MANIFEST" <<EOF
version: $VERSION
arch: arm64
zip: $ZIP_NAME
sha256: $SHA
size_mb: $SIZE_MB
built_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
cat "$MANIFEST"

if [[ "$PUBLISH" -eq 1 ]]; then
    echo "===== [+] gh release create v$VERSION ====="
    cd "$ROOT"
    gh release create "v$VERSION" "$ZIP_PATH" "$MANIFEST" \
        --title "v$VERSION" \
        --notes "MIMI v$VERSION — see CHANGELOG. sha256: \`$SHA\`"
    echo "released → https://github.com/marlonxie/MIMI/releases/tag/v$VERSION"
    echo ""
    echo "===== next: update homebrew-mimi/Casks/mimi.rb ====="
    echo "  version \"$VERSION\""
    echo "  sha256 \"$SHA\""
else
    echo ""
    echo "(skipped gh release — re-run with '$0 $VERSION --publish' to upload)"
fi
