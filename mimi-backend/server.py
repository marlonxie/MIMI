"""MIMI 面试助手 — FastAPI + WebSocket 主服务"""

import asyncio
import json
import os
import sys

# PyInstaller frozen 环境下 stdout 默认 block-buffered（log 文件读不到实时进度）
# line-buffered 让 backend.log 实时刷新，方便 BackendLauncher 看 ollama pull / 模型加载进度
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

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
# ollama base URL：BackendLauncher 传 MIMI_OLLAMA_BASE_URL 覆盖（bundled 走 11435）；
# 否则用 config.yaml 默认（dev 直接跑 server.py 时仍可走系统 ollama 默认 11434）。
_ollama_base_url = os.environ.get(
    "MIMI_OLLAMA_BASE_URL",
    config.get("llm", {}).get("ollama_base_url"),
)
llm_manager = LLMManager(
    default_provider=config["translator"]["provider"],
    ollama_base_url=_ollama_base_url,
)

# 初始化引擎（全局单例，所有连接共享）
stt = SpeechToText(config_path)
translator = Translator(llm_manager, config_path)

# RAG 引擎（可选，仅在有索引时加载）
rag_engine = None
# Intent LLM gate（auto pipeline 第二层，跟 rag_engine 一起加载）
intent_classifier = None

# 当前活跃 WebSocket 连接 — 用于把 ollama pull 进度等系统状态广播给所有前端
# 启动时 auto-pull Qwen3 可能在前端 WS 连接前就开始；后接的连接也能拿到最新进度（缓存在 last_model_progress）
active_websockets: set[WebSocket] = set()
last_model_progress: dict[str, dict] = {}  # model_name → {completed, total, status}


async def broadcast_model_progress(model: str, completed: int, total: int, status: str):
    """ollama pull / mlx-whisper download 时把进度推给所有连上的前端 onboarding。"""
    msg = {
        "type": "model_loading",
        "model": model,
        "completed": completed,
        "total": total,
        "status": status,
    }
    last_model_progress[model] = msg
    dead = []
    for ws in list(active_websockets):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        active_websockets.discard(ws)


async def ensure_ollama_model_pulled():
    """启动后台任务：检测 Qwen3 是否已在 bundled ollama，缺失则 ollama pull
    并把进度广播给前端。**仅在 active_provider 是 ollama 时跑**（用户配了 cloud key 不拉本地模型）。"""
    print(f"[ollama] ensure_ollama_model_pulled triggered, active={llm_manager.active_provider}, base_url={llm_manager._ollama_base_url}")
    if llm_manager.active_provider != "ollama":
        print("[ollama] active_provider 非 ollama，跳过")
        return
    base_url = llm_manager._ollama_base_url
    if not base_url:
        print("[ollama] base_url 未配，跳过")
        return
    from llm.providers import default_model_for
    target_model = default_model_for("ollama")

    import httpx
    # 等 daemon 起来（BackendLauncher 已经先起 ollama，这里再保险等一下）
    for _ in range(30):
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(f"{base_url}/api/version", timeout=2)
                if r.status_code == 200:
                    break
        except Exception:
            pass
        await asyncio.sleep(1)
    else:
        print("[ollama] daemon 未就绪，跳过 model pull")
        return

    async with httpx.AsyncClient(timeout=None) as c:
        # 列已装模型
        try:
            r = await c.get(f"{base_url}/api/tags", timeout=5)
            installed = {m["name"] for m in r.json().get("models", [])}
        except Exception as e:
            print(f"[ollama] api/tags 失败: {e}")
            return
        if target_model in installed:
            print(f"[ollama] {target_model} 已存在，跳过 pull")
            return

        print(f"[ollama] 拉模型 {target_model}（首次启动 ~2.6GB）...")
        try:
            async with c.stream(
                "POST", f"{base_url}/api/pull",
                json={"name": target_model},
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    status = evt.get("status", "")
                    completed = int(evt.get("completed", 0))
                    total = int(evt.get("total", 0))
                    if total > 0:
                        await broadcast_model_progress("qwen3", completed, total, status)
            # 拉完
            await broadcast_model_progress("qwen3", 1, 1, "ready")
            print(f"[ollama] {target_model} pull 完成")
        except Exception as e:
            print(f"[ollama] pull 失败: {e}")




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

    # 后台拉 Qwen3 模型（不阻塞 startup —— uvicorn 立刻接受 WS；前端 onboarding 拿进度）
    asyncio.create_task(ensure_ollama_model_pulled())

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
    # 多个 elif 分支会写 rag_engine / intent_classifier；Python 静态分析要求
    # global 声明必须在任何使用之前出现，所以集中在函数顶部声明一次。
    global rag_engine, intent_classifier

    await websocket.accept()
    # 注册到 broadcast 列表 + 立刻推一次缓存的最新模型进度（onboarding 即用）
    active_websockets.add(websocket)
    for cached in last_model_progress.values():
        try:
            await websocket.send_json(cached)
        except Exception:
            pass

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

                elif msg_type == "list_resources":
                    from rag.resources import list_resources
                    rsrc_dir = Path(config["rag"]["resources_path"]).expanduser()
                    await websocket.send_json({
                        "type": "resources_list",
                        "files": list_resources(rsrc_dir),
                    })

                elif msg_type == "delete_resource":
                    # 删完触发 reindex，复用 rebuild_index 的 release+rebuild 模式
                    from rag.resources import delete_resource
                    name = data.get("name", "")
                    rsrc_dir = Path(config["rag"]["resources_path"]).expanduser()
                    ok, reason = delete_resource(rsrc_dir, name)
                    if not ok:
                        print(f"[resources] delete failed: name={name!r} reason={reason}")
                        await websocket.send_json({
                            "type": "delete_resource_ack",
                            "ok": False,
                            "error": reason,
                        })
                    else:
                        try:
                            from rag.indexer import RAGIndexer
                            from rag.engine import RAGEngine
                            if rag_engine is not None:
                                rag_engine.release_index()
                            indexer = RAGIndexer()
                            _, files_count = indexer.index()
                            if rag_engine is not None and files_count > 0:
                                rag_engine.reload_index()
                            elif rag_engine is None and files_count > 0:
                                rag_engine = RAGEngine(llm_manager, config_path)
                                if intent_classifier is None:
                                    intent_classifier = IntentClassifier(llm_manager)
                            await websocket.send_json({
                                "type": "delete_resource_ack",
                                "ok": True,
                                "remaining": files_count,
                            })
                        except Exception as e:
                            await websocket.send_json({
                                "type": "delete_resource_ack",
                                "ok": False,
                                "error": str(e),
                            })

                elif msg_type == "clear_resources":
                    from rag.resources import clear_resources
                    rsrc_dir = Path(config["rag"]["resources_path"]).expanduser()
                    chroma_dir = Path(config["rag"]["chroma_path"]).expanduser()
                    if rag_engine is not None:
                        rag_engine.release_index()
                        rag_engine = None
                    clear_resources(rsrc_dir, chroma_dir)
                    await websocket.send_json({"type": "clear_resources_ack"})

                elif msg_type == "rebuild_index":
                    # 前端上传 RAG 资料后触发：跑 indexer + 让 RAG engine 重新加载向量库
                    try:
                        from rag.indexer import RAGIndexer
                        from rag.engine import RAGEngine
                        print("[index] 重建中...")
                        # 关键：indexer 会 rmtree chroma_store 整个目录。如果 RAGEngine
                        # 已经持有 Chroma 实例（lifespan 启动加载或前一次 rebuild 创建过），
                        # 老 SQLite handle 会被 unlink 后变 zombie，新 Chroma.from_documents
                        # 报 SQLITE_CANTOPEN (code 14)。先释放老 handle 才能干净重建。
                        if rag_engine is not None:
                            rag_engine.release_index()
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
                    # local provider 无需 key；remote provider 接受空 key 当且仅当
                    # backend 已经有这个 provider 的 key（.env 加载或之前 set 过）
                    # —— 让用户切到 ollama 再切回 gemini 时不需要重新粘 key。
                    from llm.providers import PROVIDER_MAP
                    is_local = PROVIDER_MAP.get(provider, {}).get("kind") == "local"
                    if not is_local and not api_key and not llm_manager.has_key(provider):
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
        active_websockets.discard(websocket)
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
