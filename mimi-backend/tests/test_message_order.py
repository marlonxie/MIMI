"""测试 WebSocket 消息时序 — 验证 final 总是在下一个 partial 之前到达。

核心规则：同一 speaker 任何时刻最多只有 1 个活跃 partial sentence_id。
违反则说明灰色行会重复堆积。

需要后端运行：
    cd mimi-backend && /Users/marlon/anaconda3/envs/mimi/bin/python server.py
然后跑：
    /Users/marlon/anaconda3/envs/mimi/bin/python tests/test_message_order.py
"""

import asyncio
import json
import wave
import sys
from pathlib import Path

import numpy as np

# pip install websockets (如果没装)
try:
    import websockets
except ImportError:
    print("需要 websockets 库: pip install websockets")
    sys.exit(1)

AUDIO_PATH = Path(__file__).parent / "test_audio.wav"
WS_URL = "ws://127.0.0.1:8765/ws"
CHUNK_SECONDS = 1.0


def load_audio_float32(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return audio, sr


async def run_test():
    audio, sr = load_audio_float32(AUDIO_PATH)
    chunk_samples = int(sr * CHUNK_SECONDS)
    messages = []

    async with websockets.connect(WS_URL) as ws:
        # 异步收消息的任务
        async def receiver():
            try:
                while True:
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    messages.append(msg)
            except websockets.ConnectionClosed:
                pass

        recv_task = asyncio.create_task(receiver())

        # 逐块发送音频，模拟实时
        for i in range(0, len(audio), chunk_samples):
            chunk = audio[i:i + chunk_samples]
            audio_bytes = chunk.astype(np.float32).tobytes()
            # 前缀字节 0x00 = interviewer
            payload = bytes([0x00]) + audio_bytes
            await ws.send(payload)
            # 等 1.1s 模拟实时间隔（给后端足够处理时间）
            await asyncio.sleep(1.1)

        # 发 flush
        await ws.send(json.dumps({"type": "flush"}))
        await asyncio.sleep(3.0)  # 等翻译完成

        recv_task.cancel()
        try:
            await recv_task
        except asyncio.CancelledError:
            pass

    return messages


def analyze_messages(messages: list[dict]):
    """分析消息序列，验证核心规则。"""
    transcript_msgs = [m for m in messages if m.get("type") == "transcript"]
    print(f"\n收到 {len(messages)} 条消息，其中 {len(transcript_msgs)} 条 transcript")

    # 打印 transcript 消息摘要
    for i, m in enumerate(transcript_msgs):
        final = "FINAL" if m.get("is_final") else "partial"
        text = m.get("text", "")[:60]
        sid = m.get("sentence_id", "")[:8]
        speaker = m.get("speaker", "?")
        print(f"  [{i:3d}] {final:7s} {speaker:12s} {sid}... {text}")

    # 核心断言：同一 speaker 不应同时有 >1 个活跃 partial
    active_partials: dict[str, set] = {}
    violations = []
    for i, m in enumerate(transcript_msgs):
        speaker = m["speaker"]
        sid = m["sentence_id"]
        if m.get("is_final"):
            active_partials.get(speaker, set()).discard(sid)
        else:
            active_partials.setdefault(speaker, set()).add(sid)
            if len(active_partials[speaker]) > 1:
                violations.append((i, speaker, active_partials[speaker].copy()))

    if violations:
        print(f"\n❌ 发现 {len(violations)} 个重复行违规：")
        for idx, speaker, sids in violations[:5]:
            print(f"  消息 #{idx}: speaker '{speaker}' 有 {len(sids)} 个活跃 partial: {sids}")
        return False
    else:
        print("\n✅ 消息时序正确：同一 speaker 始终只有 ≤1 个活跃 partial")
        return True


def main():
    print("=" * 60)
    print("WebSocket 消息时序测试")
    print(f"音频: {AUDIO_PATH}")
    print(f"服务: {WS_URL}")
    print("=" * 60)

    messages = asyncio.run(run_test())
    ok = analyze_messages(messages)

    if ok:
        print("\n测试通过 ✓")
    else:
        print("\n测试失败 ✗")
        sys.exit(1)


if __name__ == "__main__":
    main()
