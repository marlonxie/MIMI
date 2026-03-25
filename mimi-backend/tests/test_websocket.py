"""测试 WebSocket 服务端点"""

import asyncio
import json
import numpy as np
import websockets


async def test_websocket_connection():
    """测试：WebSocket 连接和配置"""
    uri = "ws://127.0.0.1:8765/ws"
    print(f"连接到 {uri} ...")

    async with websockets.connect(uri) as ws:
        # 发送配置
        await ws.send(json.dumps({"type": "config", "source": "interviewer"}))
        response = await ws.recv()
        data = json.loads(response)
        print(f"配置确认: {data}")
        assert data["type"] == "config_ack"
        assert data["source"] == "interviewer"

        # 发送一段模拟音频（3 秒正弦波，模拟有声音的输入）
        sample_rate = 16000
        duration = 3
        t = np.linspace(0, duration, sample_rate * duration, dtype=np.float32)
        # 440Hz 正弦波（虽然不是人声，但可以测试管道是否工作）
        audio = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        await ws.send(audio.tobytes())

        print("已发送 3 秒测试音频，等待响应...")
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=30)
            data = json.loads(response)
            print(f"收到响应: {json.dumps(data, ensure_ascii=False, indent=2)}")
        except asyncio.TimeoutError:
            print("超时（30秒内未收到响应，可能音频被判定为无语音）")

    print("连接已关闭")


if __name__ == "__main__":
    print("=" * 50)
    print("MIMI WebSocket 测试")
    print("=" * 50)
    print("注意：需要先启动服务 (python server.py)\n")

    asyncio.run(test_websocket_connection())
    print("\n测试完成!")
