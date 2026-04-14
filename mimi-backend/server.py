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

    服务端返回三种字幕消息（按句子 sentence_id 关联）:
        {"type": "transcript", ...}          → 英文识别结果（is_final 区分最终/部分）
        {"type": "translation_delta", ...}   → 中文翻译流式 token 增量
        {"type": "translation_final", ...}   → 中文翻译完成（完整文本）
    以及 RAG 提示消息:
        {"type": "suggestion", ...}          → 回答提示区（debounce 触发）
    """
    await websocket.accept()
    sample_rate = config["audio"]["sample_rate"]
    conversation = ConversationManager(
        context_window_size=config.get("conversation", {}).get("context_window_size", 10),
        export_path=config.get("conversation", {}).get("export_path", "./transcripts"),
    )
    # 每个 speaker 一个 StreamingSTT 实例（独立维护各自的累积音频缓冲）
    streaming_stts: dict[str, StreamingSTT] = {}
    # 每个 speaker 当前未结束的 partial sentence_id（让前端原地更新同一行）
    current_partial_ids: dict[str, str] = {}

    suggestion_task: asyncio.Task | None = None
    debounce_delay = config.get("conversation", {}).get("suggestion_debounce", 3.0)
    enable_suggestion = config.get("conversation", {}).get("enable_suggestion", True)
    print("WebSocket 客户端已连接")

    def get_stream(speaker: str) -> StreamingSTT:
        if speaker not in streaming_stts:
            streaming_stts[speaker] = StreamingSTT(stt, sample_rate=sample_rate)
        return streaming_stts[speaker]

    try:
        while True:
            message = await websocket.receive()

            # 处理文本消息（配置/控制命令）
            if "text" in message:
                data = json.loads(message["text"])
                msg_type = data.get("type")

                if msg_type == "config":
                    await websocket.send_json({"type": "config_ack"})

                elif msg_type == "export":
                    filepath = conversation.export_transcript()
                    await websocket.send_json({"type": "export_ack", "path": filepath})

                elif msg_type == "flush":
                    # 强制提交所有 speaker 的剩余音频
                    for speaker, stream in streaming_stts.items():
                        final = stream.flush()
                        if final.confirmed_text:
                            await _process_confirmed_text(
                                websocket, conversation, speaker,
                                final.confirmed_text, final.language,
                                current_partial_ids,
                            )
                    # ConversationManager 里可能还有 pending 文本（无句末标点）
                    flushed = conversation.flush()
                    for sentence in flushed:
                        sentence_id = current_partial_ids.pop(sentence["speaker"], None) or str(uuid.uuid4())
                        # 同步推 final + 后台翻译（和主循环一致）
                        await websocket.send_json({
                            "type": "transcript",
                            "sentence_id": sentence_id,
                            "speaker": sentence["speaker"],
                            "language": sentence["language"],
                            "text": sentence["text"],
                            "is_final": True,
                            "timestamp": sentence["timestamp"],
                        })
                        asyncio.create_task(
                            _stream_translation(websocket, sentence, conversation, sentence_id)
                        )

                continue

            # 处理二进制消息（音频数据，前 1 字节 = source 标记）
            if "bytes" in message:
                raw = message["bytes"]
                if len(raw) < 2:
                    continue
                # 前 1 字节：0x00 = interviewer, 0x01 = me
                source = "me" if raw[0] == 0x01 else "interviewer"
                audio_data = np.frombuffer(raw[1:], dtype=np.float32)

                # 跳过太短的音频
                if len(audio_data) < sample_rate * 0.3:
                    continue

                # 路由到对应 speaker 的 StreamingSTT
                # to_thread: Whisper 推理（CPU/GPU 密集）在线程池跑，不阻塞事件循环
                stream = get_stream(source)
                result = await asyncio.to_thread(stream.feed, audio_data)

                # === 处理 confirmed (LocalAgreement-2 已稳定) 文本 ===
                triggered_sentences = []
                if result.confirmed_text:
                    triggered_sentences = await _process_confirmed_text(
                        websocket, conversation, source,
                        result.confirmed_text, result.language,
                        current_partial_ids,
                    )

                    # RAG suggestion debounce — 任何面试官的完整句子都触发
                    for sentence in triggered_sentences:
                        if sentence["speaker"] == "interviewer" and rag_engine and enable_suggestion:
                            if suggestion_task and not suggestion_task.done():
                                suggestion_task.cancel()
                            suggestion_task = asyncio.create_task(
                                _debounce_suggestion(
                                    websocket, conversation, rag_engine,
                                    sentence["language"], debounce_delay
                                )
                            )

                # === 推送 partial transcript（pending + tentative） ===
                pending = ""
                if conversation.pending_speaker == source and conversation.pending_text:
                    pending = conversation.pending_text
                preview = pending
                if result.tentative_text:
                    preview = (pending + " " + result.tentative_text).strip() if pending else result.tentative_text

                if preview:
                    if source not in current_partial_ids:
                        current_partial_ids[source] = str(uuid.uuid4())
                    await websocket.send_json({
                        "type": "transcript",
                        "sentence_id": current_partial_ids[source],
                        "speaker": source,
                        "language": result.language,
                        "text": preview,
                        "is_final": False,
                        "timestamp": conversation.current_timestamp(),
                    })

    except (WebSocketDisconnect, RuntimeError):
        # RuntimeError 发生在客户端已断连后再调 receive() / send_json()
        pass
    except Exception as e:
        print(f"WebSocket 错误: {e}")
        import traceback; traceback.print_exc()
    finally:
        if suggestion_task and not suggestion_task.done():
            suggestion_task.cancel()
        if conversation.history:
            filepath = conversation.export_transcript()
            print(f"对话记录已保存: {filepath}")
        print("WebSocket 客户端断开连接")


async def _process_confirmed_text(
    websocket: WebSocket,
    conversation: ConversationManager,
    speaker: str,
    confirmed_text: str,
    language: str,
    current_partial_ids: dict,
) -> list[dict]:
    """把 StreamingSTT 提交的稳定文本喂给 ConversationManager 分句。

    对完成的句子：同步推 final transcript（保证在下一个 partial 之前到达前端），
    翻译扔后台 create_task。

    如果 confirmed 文本进了 pending（无句末标点），不 pop partial_id，
    灰色行继续用同一个 ID 更新。
    """
    completed = conversation.add_transcription(
        {"text": confirmed_text, "language": language, "segments": []},
        speaker=speaker,
    )

    if not completed:
        # confirmed 进了 ConversationManager 的 pending（没有句末标点）
        # 不 pop partial_id！灰色行继续用同一个 ID
        return []

    # 有完成的句子 → pop partial_id，同步推 final
    prev_id = current_partial_ids.pop(speaker, None) or str(uuid.uuid4())
    for i, sentence in enumerate(completed):
        sentence_id = prev_id if i == 0 else str(uuid.uuid4())
        insert_after = prev_id if i > 0 else None

        # final transcript 同步推（保证在下一个 partial 之前到达前端）
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
        await websocket.send_json(msg)

        # 翻译扔后台（不阻塞下一个 chunk 的处理）
        asyncio.create_task(
            _stream_translation(websocket, sentence, conversation, sentence_id)
        )
        prev_id = sentence_id
    return completed


async def _stream_translation(
    websocket: WebSocket,
    sentence: dict,
    conversation: ConversationManager,
    sentence_id: str,
):
    """后台协程：流式推翻译 delta + final。从旧 _send_transcript_and_translate 拆出。"""
    try:
        context = conversation.get_context_window()
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
