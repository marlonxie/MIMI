"""MIMI 面试助手 — FastAPI + WebSocket 主服务"""

import asyncio
import json
import numpy as np
import yaml
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from audio.source import AudioSource
from audio.speaker_id import identify_speaker
from audio.stt_mlx import SpeechToText
from conversation.history import SharedHistory
from translation.langchain_translator import Translator

# 加载配置
config_path = Path(__file__).parent / "config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

# MLX Metal GPU 不支持并发推理 — 全局锁保证同一时刻只有一路 Whisper 在跑
_whisper_lock = asyncio.Lock()

# 初始化引擎（全局单例，所有连接共享）
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
app = FastAPI(title="MIMI 面试助手", version="0.5.0", lifespan=lifespan)

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
        "version": "0.5.0",
        "rag_enabled": rag_engine is not None,
    }


# ============================================================================
# WebSocket 端点
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 端点 — 接收音频，返回字幕 + 回答提示。

    主循环只做消息分发，音频处理由 AudioSource 的独立协程完成。
    """
    await websocket.accept()
    sample_rate = config["audio"]["sample_rate"]

    # 共享对话历史（两路的句子都写入同一个 history）
    shared_history = SharedHistory(
        context_window_size=config.get("conversation", {}).get("context_window_size", 10),
        export_path=config.get("conversation", {}).get("export_path", "./transcripts"),
    )

    # 两路音频各自一个 AudioSource（独立 STT + 分句 + 推送状态）
    sources: dict[str, AudioSource] = {}
    for speaker in ("interviewer", "me"):
        sources[speaker] = AudioSource(
            speaker=speaker,
            websocket=websocket,
            stt_engine=stt,
            shared_history=shared_history,
            sample_rate=sample_rate,
            whisper_lock=_whisper_lock,
            translator=translator,
        )

    suggestion_task: asyncio.Task | None = None
    debounce_delay = config.get("conversation", {}).get("suggestion_debounce", 3.0)
    enable_suggestion = config.get("conversation", {}).get("enable_suggestion", True)
    print("WebSocket 客户端已连接")

    try:
        while True:
            message = await websocket.receive()

            # === 文本消息（控制命令） ===
            if "text" in message:
                data = json.loads(message["text"])
                msg_type = data.get("type")

                if msg_type == "config":
                    await websocket.send_json({"type": "config_ack"})

                elif msg_type == "export":
                    filepath = shared_history.export_transcript()
                    await websocket.send_json({"type": "export_ack", "path": filepath})

                elif msg_type == "flush":
                    for source in sources.values():
                        await source.flush()

                elif msg_type == "set_languages":
                    interview = data.get("interview_language")
                    native = data.get("native_language")
                    if interview is not None:
                        stt.set_interview_language(interview)
                    if native is not None:
                        translator.set_native_language(native)
                    await websocket.send_json({
                        "type": "languages_ack",
                        "interview_language": stt.interview_language,
                        "native_language": translator.native_language,
                    })

                elif msg_type == "set_suggestion_enabled":
                    enable_suggestion = bool(data.get("enabled", True))
                    await websocket.send_json({
                        "type": "suggestion_ack",
                        "enabled": enable_suggestion,
                    })

                continue

            # === 二进制消息（音频） — 分发到对应 AudioSource ===
            if "bytes" in message:
                raw = message["bytes"]
                if len(raw) < 2:
                    continue
                speaker = identify_speaker(raw[0])
                audio_data = np.frombuffer(raw[1:], dtype=np.float32)
                if len(audio_data) < sample_rate * 0.3:
                    continue

                # 独立协程处理，speaker 绑定在 source 实例里不会被覆盖
                asyncio.create_task(sources[speaker].handle_chunk(audio_data))

                # RAG suggestion — 检查面试官是否有新的完成句子
                if enable_suggestion and rag_engine:
                    interviewer = sources["interviewer"]
                    if interviewer.last_triggered_sentences:
                        if suggestion_task and not suggestion_task.done():
                            suggestion_task.cancel()
                        lang = interviewer.last_triggered_sentences[-1].get("language", "en")
                        suggestion_task = asyncio.create_task(
                            _debounce_suggestion(
                                websocket, shared_history, rag_engine, lang, debounce_delay
                            )
                        )
                        interviewer.last_triggered_sentences = []

    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as e:
        print(f"WebSocket 错误: {e}")
        import traceback; traceback.print_exc()
    finally:
        if suggestion_task and not suggestion_task.done():
            suggestion_task.cancel()
        if shared_history.history:
            filepath = shared_history.export_transcript()
            print(f"对话记录已保存: {filepath}")
        print("WebSocket 客户端断开连接")


async def _debounce_suggestion(
    websocket: WebSocket,
    shared_history: SharedHistory,
    rag_engine,
    language: str,
    delay: float = 3.0,
):
    """等待 delay 秒后生成回答提示。被 cancel 说明面试官还在说话。"""
    try:
        await asyncio.sleep(delay)
        latest_text = shared_history.get_last_interviewer_text()
        if not latest_text:
            return
        context = shared_history.get_context_window()
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
        pass
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
