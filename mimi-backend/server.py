"""MIMI 面试助手 — FastAPI + WebSocket 主服务"""

import asyncio
import json
import numpy as np
import yaml
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from audio.source import AudioSource
from audio.speaker_id import identify_speaker
from audio.stt_mlx import SpeechToText
from conversation.history import SharedHistory
from conversation.intent_classifier import IntentClassifier
from conversation.question_filter import is_likely_filler
from llm import LLMManager
from translation.langchain_translator import Translator

# 启动时加载 .env（开发者路径）；前端 Settings 推送的 key 走 set_api_keys 覆盖
load_dotenv(Path(__file__).parent / ".env")

# 加载配置
config_path = Path(__file__).parent / "config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

# MLX Metal GPU 不支持并发推理 — 全局锁保证同一时刻只有一路 Whisper 在跑
_whisper_lock = asyncio.Lock()

# LLM 状态管理（缺 key 时不抛异常，组件懒就绪等 set_api_keys）
llm_manager = LLMManager(default_provider=config["translator"]["provider"])

# 初始化引擎（全局单例，所有连接共享）
stt = SpeechToText(config_path)
translator = Translator(llm_manager, config_path)

# RAG 引擎（可选，仅在有索引时加载）
rag_engine = None
# Intent LLM gate（auto pipeline 第二层，跟 rag_engine 一起加载）
intent_classifier = None


@asynccontextmanager
async def lifespan(app):
    """服务启动时预加载模型 + 创建用户数据目录"""
    global rag_engine, intent_classifier
    print("MIMI 后端启动中...")

    # 创建 ~/Library/Application Support/MIMI/{resources,transcripts,chroma_store}
    # （朋友首次启动时这些目录都不存在）
    for cfg_path in [
        config["conversation"]["export_path"],
        config["rag"]["chroma_path"],
        config["rag"]["resources_path"],
    ]:
        Path(cfg_path).expanduser().mkdir(parents=True, exist_ok=True)

    stt.load_model()

    chroma_path = Path(config["rag"]["chroma_path"]).expanduser()
    if chroma_path.exists() and any(chroma_path.iterdir()):
        try:
            from rag.engine import RAGEngine
            rag_engine = RAGEngine(llm_manager, config_path)
            intent_classifier = IntentClassifier(llm_manager)
            print(
                f"RAG 引擎已加载，Intent classifier 已初始化"
                f" (translator_ready={translator.is_ready}, rag_ready={rag_engine.is_ready})"
            )
        except Exception as e:
            print(f"RAG 引擎加载失败（跳过）: {e}")
    else:
        print("未找到 RAG 索引，前端上传 RAG 资料后会自动重建（rebuild_index）")

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

    # === Suggestion pipeline state ===
    # 同一时刻最多一个 suggestion task 在跑（auto 或 manual）。Manual 可抢占 auto。
    suggestion_task: asyncio.Task | None = None
    pending_is_manual: bool = False

    debounce_delay = config.get("conversation", {}).get("suggestion_debounce", 1.5)
    enable_suggestion = config.get("conversation", {}).get("enable_suggestion", True)
    intent_gate_enabled = config.get("conversation", {}).get("intent_gate", True)
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
                    # path 可选：UI 走 NSSavePanel 选好后传过来；CLI / 测试不传走默认目录
                    requested_path = data.get("path")
                    filepath = shared_history.export_transcript(output_path=requested_path)
                    await websocket.send_json({"type": "export_ack", "path": filepath})

                elif msg_type == "rebuild_index":
                    # 前端上传 RAG 资料后触发：跑 indexer + 让 RAG engine 重新加载向量库
                    global rag_engine, intent_classifier
                    try:
                        from rag.indexer import RAGIndexer
                        from rag.engine import RAGEngine
                        print("[index] 重建中...")
                        indexer = RAGIndexer()
                        _, files_count = indexer.index()
                        if rag_engine is None and files_count > 0:
                            # 第一次上传 + 索引：lifespan 启动时还没 RAG engine，现在创建
                            rag_engine = RAGEngine(llm_manager, config_path)
                            if intent_classifier is None:
                                intent_classifier = IntentClassifier(llm_manager)
                        elif rag_engine is not None:
                            rag_engine.reload_index()
                        await websocket.send_json({
                            "type": "rebuild_index_ack",
                            "count": files_count,
                        })
                        print(f"[index] 完成，{files_count} 个文件")
                    except Exception as e:
                        print(f"[index] 失败: {e}")
                        await websocket.send_json({
                            "type": "rebuild_index_ack",
                            "count": 0,
                            "error": str(e),
                        })

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

                elif msg_type == "set_api_keys":
                    provider = data.get("provider", "gemini")
                    api_key = data.get("api_key", "")
                    # local provider（ollama 等）无需 key；只对 remote provider 校验非空
                    from llm.providers import PROVIDER_MAP
                    is_local = PROVIDER_MAP.get(provider, {}).get("kind") == "local"
                    if not is_local and not api_key:
                        await websocket.send_json({
                            "type": "api_keys_error",
                            "reason": "empty key",
                        })
                        continue
                    was_translator_ready = translator.is_ready
                    llm_manager.set_key(provider, api_key)
                    translator.rebuild()
                    if intent_classifier:
                        intent_classifier.rebuild()
                    if rag_engine:
                        rag_engine.rebuild()
                    if was_translator_ready:
                        print(f"[api_keys] frontend override (was ready, switching to provider={provider})")
                    else:
                        print(f"[api_keys] received provider={provider}, translator_ready={translator.is_ready}")
                    await websocket.send_json({
                        "type": "api_keys_ack",
                        "provider": provider,
                        "translator_ready": translator.is_ready,
                        "rag_ready": rag_engine.is_ready if rag_engine else False,
                    })
                    continue

                elif msg_type == "query_status":
                    await websocket.send_json({
                        "type": "status",
                        "active_provider": llm_manager.active_provider,
                        "translator_ready": translator.is_ready,
                        "rag_ready": rag_engine.is_ready if rag_engine else False,
                        "rag_loaded": rag_engine is not None,
                    })
                    continue

                elif msg_type == "manual_suggest":
                    if not rag_engine or not rag_engine.is_ready:
                        await websocket.send_json({
                            "type": "suggestion_error",
                            "reason": "RAG 未启用或缺 API key",
                        })
                        continue
                    sentence_id = data.get("sentence_id", "")
                    query, focused_ctx = shared_history.get_focused_context(sentence_id)
                    if not query:
                        await websocket.send_json({
                            "type": "suggestion_error",
                            "reason": "未找到句子",
                        })
                        continue

                    # Manual 抢占一切
                    if suggestion_task and not suggestion_task.done():
                        suggestion_task.cancel()
                        print("[arb] manual 抢占：cancel 正在跑的 task")

                    suggestion_task = asyncio.create_task(
                        _run_rag_and_send(
                            websocket, rag_engine, query, focused_ctx,
                            interview_language=stt.interview_language or "en",
                            native_language=translator.native_language,
                            sentence_id=sentence_id,
                        )
                    )
                    pending_is_manual = True
                    print(f"[manual] sentence_id={sentence_id}")

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

                # === Auto suggestion pipeline (A: filter → B: intent → C: RAG) ===
                # 缺 api key 时（rag_engine.is_ready=False）跳过，避免空跑
                if (enable_suggestion and rag_engine and rag_engine.is_ready
                        and intent_classifier):
                    interviewer = sources["interviewer"]
                    if interviewer.last_triggered_sentences:
                        latest_sentence = interviewer.last_triggered_sentences[-1]
                        lang = latest_sentence.get("language", "en")

                        # Manual 跑中 → auto 放弃
                        if (suggestion_task and not suggestion_task.done()
                                and pending_is_manual):
                            print(f"[arb] auto 跳过（manual pending）: "
                                  f"{latest_sentence['text'][:40]!r}")
                            interviewer.last_triggered_sentences = []
                            continue

                        # [A] 本地过滤
                        if is_likely_filler(latest_sentence["text"], lang):
                            print(f"[filter] drop: {latest_sentence['text']!r}")
                            interviewer.last_triggered_sentences = []
                            continue

                        # Cancel 旧的 auto（新句来了用最新的）
                        if suggestion_task and not suggestion_task.done():
                            suggestion_task.cancel()

                        suggestion_task = asyncio.create_task(
                            _auto_pipeline(
                                websocket, shared_history, rag_engine,
                                intent_classifier, latest_sentence["text"], lang,
                                intent_gate_enabled,
                                interview_language=stt.interview_language or "en",
                                native_language=translator.native_language,
                                debounce_delay=debounce_delay,
                            )
                        )
                        pending_is_manual = False
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


async def _auto_pipeline(
    websocket: WebSocket,
    shared_history: SharedHistory,
    rag_engine,
    intent_classifier: IntentClassifier,
    trigger_text: str,
    language: str,
    intent_gate_enabled: bool,
    interview_language: str,
    native_language: str,
    debounce_delay: float,
):
    """Auto path：短 debounce + [B] intent gate + [C] RAG。被 cancel 意味着新句子到了。"""
    try:
        # 短 debounce 让连续句子归并
        await asyncio.sleep(min(debounce_delay, 1.5))

        # RAG query 用完整 interviewer 独白（不只是最新一句）
        latest_text = shared_history.get_last_interviewer_text()
        if not latest_text:
            return
        context = shared_history.get_context_window()

        # [B] Intent gate
        if intent_gate_enabled:
            is_question = await intent_classifier.should_respond(
                latest_text, context, language,
            )
            if not is_question:
                print(f"[intent] no : {latest_text[:80]!r}")
                return
            print(f"[intent] yes: {latest_text[:80]!r}")

        # [C] RAG 生成 + 推送
        await _run_rag_and_send(
            websocket, rag_engine, latest_text, context,
            interview_language=interview_language,
            native_language=native_language,
            sentence_id=None,
        )
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[auto] pipeline error: {e}")


async def _run_rag_and_send(
    websocket: WebSocket,
    rag_engine,
    query: str,
    context: str,
    interview_language: str,
    native_language: str,
    sentence_id: str | None,
):
    """单纯的 RAG 生成 + WebSocket 推送。manual / auto 共用。"""
    try:
        print(f"[rag] start  query={query[:60]!r}")
        suggestion = await rag_engine.generate_suggestion(
            latest_text=query,
            interview_language=interview_language,
            native_language=native_language,
            conversation_context=context,
        )
        payload = {
            "type": "suggestion",
            "suggestion": suggestion["suggestion"],
            "sources": suggestion["sources"],
        }
        if sentence_id:
            payload["sentence_id"] = sentence_id
        await websocket.send_json(payload)
        print(f"[rag] done   sources={suggestion['sources']}")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"[rag] error: {e}")


if __name__ == "__main__":
    import sys
    import argparse
    import multiprocessing
    import uvicorn

    # PyInstaller 打包必需：huggingface_hub.snapshot_download 用 multiprocessing.Pool
    # 并行下载，worker 进程被 fork 后会重新执行 __main__；freeze_support 让 worker
    # 识别自己并退出，避免 fork bomb（每个 worker 都试图启 uvicorn）
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(prog="mimi-backend")
    parser.add_argument(
        "--prefetch-model",
        action="store_true",
        help="下载 mlx-whisper 模型后立即退出（brew cask postflight 用，让 ~500MB 下载发生在终端而非 app 首次启动）",
    )
    args = parser.parse_args()

    if args.prefetch_model:
        # 触发 mlx-whisper 模型从 HuggingFace 下载到 ~/.cache/huggingface/
        # 不启 WS server，下完即退出
        import numpy as np
        from audio.stt_mlx import SpeechToText
        print("正在下载语音模型 (mlx-community/whisper-small-mlx, ~500MB)...")
        stt = SpeechToText()
        # 跑一次空 transcribe 强制 mlx 把 weights 真正 load 进来（构造时只下载文件元数据）
        stt.transcribe_audio(np.zeros(16000, dtype=np.float32))
        print("✓ 模型下载完成，缓存在 ~/.cache/huggingface/")
        sys.exit(0)

    # PyInstaller 打包后 sys.frozen=True；frozen 状态下 reload=True 会让 uvicorn
    # 试图 spawn 子进程 import "server:app"，但 module 已被打包，spawn 失败 → 端口 listen 不起来
    if getattr(sys, "frozen", False):
        uvicorn.run(
            app,
            host=config["server"]["host"],
            port=config["server"]["port"],
        )
    else:
        uvicorn.run(
            "server:app",
            host=config["server"]["host"],
            port=config["server"]["port"],
            reload=True,
        )
