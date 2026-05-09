#!/usr/bin/env bash
# macOS 26 Tahoe CoreAudio degraded-state recovery.
#
# Symptom: ScreenCaptureKit / 任何 audio capture 开始返回 -36 dB 衰减信号
# (peak ~0.015 而非正常的 0.1-0.5)，导致 STT 识别全空。
#
# 根因: 某个 CoreAudio client 进程污染共享 HAL 状态后，所有后续 capture session
# 继承被污染状态。`killall coreaudiod` 单独无效——存活 client (尤其 Xcode +
# CoreSimulator) 会在 ~1s 内重新污染回去。
#
# 用法: 跑这个脚本前先关掉 Xcode / Simulator / 重音频 app (Spotify lossless 等)，
# 然后 `bash fix_audio.sh`，再重启 MIMI.
#
# 持久性: 不持久。下次某个 client 又会污染。Apple 修 bug 之前没有永久 fix。
# 参考: https://gist.github.com/metrovoc/0b5e3590c6069cf99b01559863bc2ce4
set -e

echo "[1/3] 杀光所有 CoreAudio client (保留 6 个守护进程)..."
SKIP='coreaudiod|audiomxd|audioclocksyncd|audioanalyticsd|audioaccessoryd|AudioComponentRegistrar|audio.DriverHelper|audio.SandboxHelper|ParrotAudioPlugin'
lsof 2>/dev/null | grep CoreAudio | awk '{print $2, $1}' \
  | sort -t' ' -k1,1 -un | grep -vE "$SKIP" \
  | while read pid name; do
      echo "  kill $name ($pid)"
      kill -9 "$pid" 2>/dev/null || true
    done

echo "[2/3] 干掉 Xcode + Simulator (重污染重灾区)..."
killall Xcode SimulatorTrampoline com.apple.CoreSimulator.CoreSimulatorService simdiskimaged 2>/dev/null || true
sleep 1

echo "[3/3] 重启 6 个 audio 守护进程 (需要 sudo)..."
sudo killall -9 coreaudiod audiomxd audioclocksyncd audioanalyticsd \
                audioaccessoryd AudioComponentRegistrar 2>/dev/null || true

echo
echo "完成。重新启动 MimiApp，立刻播一段音频测试。"
echo "Tip: tail -f /tmp/mimi-server.log | grep interviewer 看 peak 值。"
echo "正常应该 0.1+，如果还是 0.015 → 又被污染了，重启 Mac。"
