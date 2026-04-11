"""MIMI 面试助手 — FastAPI + WebSocket 主服务"""

import asyncio
import json
import numpy as np
import yaml
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core.stt import SpeechToText
from core.translator import Translator
from core.conversation import ConversationManager

# 加载配置
config_path = Path(__file__).parent / "config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

# 初始化模块
stt = SpeechToText(config_path)
translator = Translator(config_path)

# RAG 引擎（可选，仅在有索引时加载）
rag_engine = None


@asynccontextmanager
async def lifespan(app):
    """服务启动时预加载模型"""
    global rag_engine
    print("MIMI 后端启动中...")
    stt.load_model()

    # 尝试加载 RAG 引擎
    chroma_path = Path(__file__).parent / config["rag"]["chroma_path"]
    if chroma_path.exists() and any(chroma_path.iterdir()):
        try:
            from rag.engine import RAGEngine
            rag_engine = RAGEngine(config_path)
            print("RAG 引擎已加载")
        except Exception as e:
            print(f"RAG 引擎加载失败（跳过）: {e}")
    else:
        print("未找到 RAG 索引，回答提示功能未启用。运行 python -m rag.indexer 创建索引")

    print(f"服务运行在 {config['server']['host']}:{config['server']['port']}")
    yield


# 初始化 FastAPI
app = FastAPI(title="MIMI 面试助手", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "0.3.0",
        "rag_enabled": rag_engine is not None,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 端点 — 接收音频，返回翻译 + 回答提示

    客户端发送:
        二进制音频数据（PCM float32, 16kHz）
        或 JSON: {"type": "config", "source": "interviewer"|"me"}
        或 JSON: {"type": "export"} — 导出对话记录
        或 JSON: {"type": "flush"} — 强制输出 pending 文本

    服务端返回两种消息:
        {"type": "translation", ...}   → 翻译区
        {"type": "suggestion", ...}    → 回答提示区（debounce 触发）
    """
    await websocket.accept()
    source = "interviewer"
    conversation = ConversationManager(
        context_window_size=config.get("conversation", {}).get("context_window_size", 10),
        export_path=config.get("conversation", {}).get("export_path", "./transcripts"),
    )
    suggestion_task: asyncio.Task | None = None
    debounce_delay = config.get("conversation", {}).get("suggestion_debounce", 3.0)
    enable_suggestion = config.get("conversation", {}).get("enable_suggestion", True)
    print("WebSocket 客户端已连接")

    try:
        while True:
            message = await websocket.receive()

            # 处理文本消息（配置/控制命令）
            if "text" in message:
                data = json.loads(message["text"])
                msg_type = data.get("type")

                if msg_type == "config":
                    source = data.get("source", source)
                    await websocket.send_json({"type": "config_ack", "source": source})

                elif msg_type == "export":
                    filepath = conversation.export_transcript()
                    await websocket.send_json({"type": "export_ack", "path": filepath})

                elif msg_type == "flush":
                    flushed = conversation.flush()
                    for sentence in flushed:
                        await _send_translation(websocket, sentence, conversation)

                continue

            # 处理二进制消息（音频数据）
            if "bytes" in message:
                audio_bytes = message["bytes"]
                audio_data = np.frombuffer(audio_bytes, dtype=np.float32)

                # 跳过太短的音频（小于 0.5 秒）
                if len(audio_data) < config["audio"]["sample_rate"] * 0.5:
                    continue

                # STT 转写
                stt_result = stt.transcribe_audio(audio_data)
                if not stt_result["text"]:
                    continue

                # 对话管理器：分句
                completed_sentences = conversation.add_transcription(stt_result, speaker=source)

                # 处理每个完成的句子
                for sentence in completed_sentences:
                    # 翻译区：每句话立即翻译
                    await _send_translation(websocket, sentence, conversation)

                    # 回答提示区：面试官说话时启动/重置 debounce 计时器
                    if sentence["speaker"] == "interviewer" and rag_engine and enable_suggestion:
                        if suggestion_task and not suggestion_task.done():
                            suggestion_task.cancel()
                        suggestion_task = asyncio.create_task(
                            _debounce_suggestion(
                                websocket, conversation, rag_engine,
                                sentence["language"], debounce_delay
                            )
                        )

    except WebSocketDisconnect:
        if suggestion_task and not suggestion_task.done():
            suggestion_task.cancel()
        if conversation.history:
            filepath = conversation.export_transcript()
            print(f"对话记录已保存: {filepath}")
        print("WebSocket 客户端断开连接")
    except Exception as e:
        if suggestion_task and not suggestion_task.done():
            suggestion_task.cancel()
        print(f"WebSocket 错误: {e}")


async def _send_translation(
    websocket: WebSocket,
    sentence: dict,
    conversation: ConversationManager,
):
    """翻译并发送一个完成的句子"""
    context = conversation.get_context_window()
    translation_result = await translator.translate_async(
        sentence["text"], sentence["language"], context=context
    )
    await websocket.send_json({
        "type": "translation",
        "speaker": sentence["speaker"],
        "original": sentence["text"],
        "language": sentence["language"],
        "translation": translation_result["translation"],
        "timestamp": sentence["timestamp"],
    })


async def _debounce_suggestion(
    websocket: WebSocket,
    conversation: ConversationManager,
    rag_engine,
    language: str,
    delay: float = 3.0,
):
    """等待 delay 秒后生成回答提示。被 cancel 说明面试官还在说话。"""
    try:
        await asyncio.sleep(delay)
        latest_text = conversation.get_last_interviewer_text()
        if not latest_text:
            return
        context = conversation.get_context_window()
        suggestion = await rag_engine.generate_suggestion(
            latest_text=latest_text,
            language=language,
            conversation_context=context,
        )
        await websocket.send_json({
            "type": "suggestion",
            "suggestion": suggestion["suggestion"],
            "sources": suggestion["sources"],
        })
    except asyncio.CancelledError:
        pass  # 被取消说明面试官还在说话，正常行为
    except Exception as e:
        print(f"RAG 提示生成失败: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host=config["server"]["host"],
        port=config["server"]["port"],
        reload=True,
    )
