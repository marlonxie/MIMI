"""测试 WebSocket 服务端点"""

import asyncio
import json
import wave
import numpy as np
import websockets

URI = "ws://127.0.0.1:8765/ws"


async def test_config():
    """测试：WebSocket 连接和配置"""
    print(f"连接到 {URI} ...")
    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps({"type": "config", "source": "interviewer"}))
        response = await ws.recv()
        data = json.loads(response)
        assert data["type"] == "config_ack"
        assert data["source"] == "interviewer"
        print(f"  配置确认: {data} ✓")


async def test_silence():
    """测试：发送正弦波（非人声），应无 translation 响应"""
    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps({"type": "config", "source": "interviewer"}))
        await ws.recv()  # config_ack

        sample_rate = 16000
        t = np.linspace(0, 3, sample_rate * 3, dtype=np.float32)
        audio = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        await ws.send(audio.tobytes())

        try:
            response = await asyncio.wait_for(ws.recv(), timeout=15)
            data = json.loads(response)
            print(f"  收到响应（可能 Whisper 识别出了什么）: type={data.get('type')}")
        except asyncio.TimeoutError:
            print(f"  正弦波无响应（正确，非人声） ✓")


async def test_real_audio():
    """测试：发送真实音频，验证 translation 消息格式"""
    test_file = "tests/test_audio.wav"  # backend-relative path
    try:
        with wave.open(test_file, 'rb') as wf:
            sr = wf.getframerate()
            frames = wf.readframes(sr * 5)
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    except FileNotFoundError:
        print(f"  跳过：{test_file} 不存在")
        return

    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps({"type": "config", "source": "interviewer"}))
        await ws.recv()  # config_ack

        await ws.send(audio.tobytes())
        print(f"  已发送 {len(audio)/16000:.1f}s 音频，等待响应...")

        response = await asyncio.wait_for(ws.recv(), timeout=60)
        data = json.loads(response)

        # 验证新的 translation 消息格式
        assert data["type"] == "translation", f"期望 type=translation, 得到 {data['type']}"
        assert "speaker" in data
        assert "original" in data
        assert "translation" in data
        assert "language" in data
        assert "timestamp" in data
        print(f"  type: {data['type']} ✓")
        print(f"  speaker: {data['speaker']}")
        print(f"  original: {data['original'][:60]}...")
        print(f"  translation: {data['translation'][:60]}...")
        print(f"  language: {data['language']}")
        print(f"  真实音频端到端测试通过 ✓")


async def test_export():
    """测试：export 命令"""
    async with websockets.connect(URI) as ws:
        # 先发一段音频让 conversation 有内容
        await ws.send(json.dumps({"type": "config", "source": "interviewer"}))
        await ws.recv()  # config_ack

        # 导出（即使没有 history 也应返回 export_ack）
        await ws.send(json.dumps({"type": "export"}))
        response = await asyncio.wait_for(ws.recv(), timeout=10)
        data = json.loads(response)
        assert data["type"] == "export_ack"
        assert "path" in data
        print(f"  export 命令: path={data['path']} ✓")


async def test_flush():
    """测试：flush 命令"""
    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps({"type": "config", "source": "interviewer"}))
        await ws.recv()  # config_ack

        # flush 空 pending 不应返回消息
        await ws.send(json.dumps({"type": "flush"}))
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=3)
            data = json.loads(response)
            print(f"  flush 收到响应: type={data.get('type')}")
        except asyncio.TimeoutError:
            print(f"  flush 空 pending: 无响应（正确） ✓")


if __name__ == "__main__":
    print("=" * 50)
    print("MIMI WebSocket 测试")
    print("=" * 50)
    print("注意：需要先启动服务 (python server.py)\n")

    print("--- 测试配置 ---")
    asyncio.run(test_config())

    print("\n--- 测试正弦波（非人声）---")
    asyncio.run(test_silence())

    print("\n--- 测试真实音频 ---")
    asyncio.run(test_real_audio())

    print("\n--- 测试 export 命令 ---")
    asyncio.run(test_export())

    print("\n--- 测试 flush 命令 ---")
    asyncio.run(test_flush())

    print("\n所有测试完成!")
