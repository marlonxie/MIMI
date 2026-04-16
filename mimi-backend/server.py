"""MIMI 面试助手 — FastAPI + WebSocket 主服务"""

import asyncio
import json
import uuid
import numpy as np
import yaml
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core.stt import SpeechToText
from core.stt_stream import StreamingSTT
from core.translator import Translator
from core.conversation import SharedHistory, SentenceSegmenter
from core.speaker_id import identify_speaker

# 加载配置
config_path = Path(__file__).parent / "config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

# MLX Metal GPU 不支持并发推理 — 全局锁保证同一时刻只有一路 Whisper 在跑
_whisper_lock = asyncio.Lock()

# 初始化模块（全局单例，所有连接共享）
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
app = FastAPI(title="MIMI 面试助手", version="0.4.0", lifespan=lifespan)

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
        "version": "0.4.0",
        "rag_enabled": rag_engine is not None,
    }


# ============================================================================
# AudioSource — 每个音频源（系统音频 / 麦克风）的独立处理管道
# ============================================================================

class AudioSource:
    """每个音频源的完整处理管道：STT → 分句 → 推送。

    两路音频各自一个实例，状态完全独立：
    - self.stream: StreamingSTT（独立 buffer / LocalAgreement-2）
    - self.segmenter: SentenceSegmenter（独立 pending 缓冲）
    - self.partial_id: 当前灰色行的 UUID

    speaker 字段是简化的说话人识别（系统音频→interviewer，麦克风→me），
    真正的 diarization 作为独立模块叠加（见 core/speaker_id.py）。
    """

    def __init__(
        self,
        speaker: str,
        websocket: WebSocket,
        stt_engine: SpeechToText,
        shared_history: SharedHistory,
        sample_rate: int,
    ):
        self.speaker = speaker
        self.websocket = websocket
        self.shared_history = shared_history
        self.stream = StreamingSTT(stt_engine, sample_rate=sample_rate)
        self.segmenter = SentenceSegmenter(speaker, shared_history)
        self.partial_id: str | None = None
        self.last_triggered_sentences: list[dict] = []

    def pop_partial_id(self) -> str | None:
        pid = self.partial_id
        self.partial_id = None
        return pid

    async def handle_chunk(self, audio_data: np.ndarray):
        """处理一个音频 chunk：Whisper 推理 → 分句 → final 推送 → partial 推送。

        在独立协程里跑（create_task），self.speaker 不会被其他路覆盖。
        """
        # Whisper 推理（GPU 锁保证不和另一路同时跑）
        async with _whisper_lock:
            result = await asyncio.to_thread(self.stream.feed, audio_data)

        # === confirmed 文本 → 分句 → final 推送 ===
        if result.confirmed_text:
            # 用 add_words 利用词间停顿做自然分句（而非 add_text 只看 .?!）
            completed = self.segmenter.add_words(result.confirmed_words, result.language)
            if completed:
                prev_id = self.pop_partial_id() or str(uuid.uuid4())
                for i, sentence in enumerate(completed):
                    sentence_id = prev_id if i == 0 else str(uuid.uuid4())
                    insert_after = prev_id if i > 0 else None

                    msg = {
                        "type": "transcript",
                        "sentence_id": sentence_id,
                        "speaker": sentence["speaker"],
                        "language": sentence["language"],
                        "text": sentence["text"],
                        "is_final": True,
                        "timestamp": sentence["timestamp"],
                    }
                    if insert_after is not None:
                        msg["insert_after"] = insert_after
                    await self.websocket.send_json(msg)

                    asyncio.create_task(
                        _stream_translation(self.websocket, sentence, self.shared_history, sentence_id)
                    )
                    prev_id = sentence_id
                self.last_triggered_sentences = completed

        # === partial 推送（灰色行） ===
        preview = self.segmenter.pending_text or ""
        if result.tentative_text:
            preview = (preview + " " + result.tentative_text).strip() if preview else result.tentative_text

        if preview:
            if self.partial_id is None:
                self.partial_id = str(uuid.uuid4())
            await self.websocket.send_json({
                "type": "transcript",
                "sentence_id": self.partial_id,
                "speaker": self.speaker,
                "language": result.language,
                "text": preview,
                "is_final": False,
                "timestamp": self.shared_history.current_timestamp(),
            })

    async def flush(self):
        """强制提交 StreamingSTT 剩余 buffer + SentenceSegmenter pending。"""
        # StreamingSTT flush
        final = self.stream.flush()
        if final.confirmed_text:
            completed = self.segmenter.add_words(final.confirmed_words, final.language)
            if completed:
                prev_id = self.pop_partial_id() or str(uuid.uuid4())
                for i, sentence in enumerate(completed):
                    sentence_id = prev_id if i == 0 else str(uuid.uuid4())
                    await self.websocket.send_json({
                        "type": "transcript",
                        "sentence_id": sentence_id,
                        "speaker": sentence["speaker"],
                        "language": sentence["language"],
                        "text": sentence["text"],
                        "is_final": True,
                        "timestamp": sentence["timestamp"],
                    })
                    asyncio.create_task(
                        _stream_translation(self.websocket, sentence, self.shared_history, sentence_id)
                    )
                    prev_id = sentence_id

        # SentenceSegmenter flush（pending 里可能还有没句末标点的文本）
        flushed = self.segmenter.flush()
        for sentence in flushed:
            sid = self.pop_partial_id() or str(uuid.uuid4())
            await self.websocket.send_json({
                "type": "transcript",
                "sentence_id": sid,
                "speaker": sentence["speaker"],
                "language": sentence["language"],
                "text": sentence["text"],
                "is_final": True,
                "timestamp": sentence["timestamp"],
            })
            asyncio.create_task(
                _stream_translation(self.websocket, sentence, self.shared_history, sid)
            )


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


# ============================================================================
# 辅助协程
# ============================================================================

async def _stream_translation(
    websocket: WebSocket,
    sentence: dict,
    shared_history: SharedHistory,
    sentence_id: str,
):
    """后台协程：流式推翻译 delta + final。"""
    try:
        context = shared_history.get_context_window()
        full_translation = ""
        async for delta in translator.translate_stream(
            sentence["text"], sentence["language"], context=context
        ):
            full_translation += delta
            await websocket.send_json({
                "type": "translation_delta",
                "sentence_id": sentence_id,
                "delta": delta,
            })

        await websocket.send_json({
            "type": "translation_final",
            "sentence_id": sentence_id,
            "text": full_translation.strip(),
        })
    except Exception as e:
        print(f"翻译推送中止: {type(e).__name__}")


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
