# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MIMI 面试助手 — macOS interview assistant for Mandarin native speakers doing English/German interviews. Mixed architecture: Python backend (FastAPI + WebSocket) + Swift native frontend (SwiftUI + ScreenCaptureKit).

## Commands

**Python interpreter** (conda `mimi` env has path issues with `conda run`, always use absolute path):
```bash
/Users/marlon/anaconda3/envs/mimi/bin/python
```

**Start backend server:**
```bash
cd mimi-backend && /Users/marlon/anaconda3/envs/mimi/bin/python server.py
# Listens on ws://127.0.0.1:8765
```

**Index documents for RAG:**
```bash
cd mimi-backend && /Users/marlon/anaconda3/envs/mimi/bin/python -m rag.indexer
```

**Run tests individually:**
```bash
cd mimi-backend
/Users/marlon/anaconda3/envs/mimi/bin/python tests/test_stt.py
/Users/marlon/anaconda3/envs/mimi/bin/python tests/test_stt_stream.py     # LocalAgreement-2 流式 STT
/Users/marlon/anaconda3/envs/mimi/bin/python tests/test_translator.py
/Users/marlon/anaconda3/envs/mimi/bin/python tests/test_translator_stream.py  # 流式翻译
/Users/marlon/anaconda3/envs/mimi/bin/python tests/test_message_order.py  # 双路消息时序（需要 server 运行）
/Users/marlon/anaconda3/envs/mimi/bin/python tests/test_rag.py
/Users/marlon/anaconda3/envs/mimi/bin/python tests/test_websocket.py  # requires server running
```

**Benchmark Whisper backends:**
```bash
cd mimi-backend && /Users/marlon/anaconda3/envs/mimi/bin/python scripts/bench_whisper.py
# Compares openai/whisper (CPU) vs mlx-whisper (Metal GPU+ANE) vs faster-whisper (CPU int8)
```

**Install packages:**
```bash
/Users/marlon/anaconda3/envs/mimi/bin/pip install <package>
# Required STT backend: mlx-whisper (Apple Silicon GPU+ANE)
```

## Architecture

```
Swift App (SwiftUI) ──WebSocket (binary: 1-byte source prefix + PCM)──→ Python Backend (FastAPI)
│                                                                            │
├── ScreenCaptureKit (系统音频, 0x00)                          ┌─────────────┼──────────────┐
├── AVAudioEngine (麦克风, 0x01)                               ▼             ▼              ▼
└── NSPanel (悬浮字幕窗)                              AudioSource       core/translator   rag/engine
                                                   (per-speaker 管道)   (LangChain LCEL,  (LangChain RAG,
                                                    ├── StreamingSTT    Gemini/Claude,     ChromaDB)
                                                    │   (stt_stream.py   .astream())
                                                    │    + stt.py/mlx)
                                                    ├── SentenceSegmenter
                                                    │   (独立 pending)
                                                    └── partial_id
                                                            ↓
                                                      SharedHistory (共享)
                                                      (双路对话记录 + context_window)
```

- **AudioSource**: 每个音频源（系统音频/麦克风）一个独立实例。封装 StreamingSTT + SentenceSegmenter + partial_id。两路互不干扰，通过 `asyncio.create_task` 并发处理。
- **speaker_id**: `core/speaker_id.py` 管理说话人识别。当前简化逻辑：系统音频→"interviewer"，麦克风→"me"。未来 diarization 作为独立模块叠加。
- **WebSocket message types** (字幕全部按 `sentence_id` 关联):
  - `"type": "transcript"` — 识别结果，`is_final` 区分 partial（半透明更新中）/ final（定型）
  - `"type": "translation_delta"` — 中文翻译流式 token 增量
  - `"type": "translation_final"` — 中文翻译完成（完整文本，覆盖 delta 拼接误差）
  - `"type": "suggestion"` — RAG 回答提示（debounce 触发）
- **Streaming STT pipeline**: 前端每 1s 发一块音频（带 1 字节 source 前缀）。后端按 source 分发到对应 AudioSource，各自的 StreamingSTT 维护累积音频缓冲，在整个 buffer 上重新跑 Whisper，用 **LocalAgreement-2** 算法判断稳定词。提交的稳定文本喂给 per-speaker 的 SentenceSegmenter 做分句（独立 pending），完成的句子写入 SharedHistory。
- **SharedHistory**: 双路共享的对话记录。提供 `get_context_window()` 给翻译和 RAG 用，`export_transcript()` 导出。
- **Config-driven**: All settings in `mimi-backend/config.yaml`. Switch LLM provider by changing `translator.provider` ("gemini"/"claude")
- **RAG output format**: 📌 Question understanding (Chinese) + 💡 Key points (Chinese) + 🗣️ Example answer (in interview language en/de)

## Key Conventions

- **LangChain v1 required**: Always reference LangChain v1 docs/source before writing LangChain code. Current: langchain-core 1.2.21. Use LCEL pipe syntax (`prompt | llm | parser`), `.invoke()` / `.ainvoke()` / `.astream()`
- **Environment variables**: API keys in `mimi-backend/.env` (loaded via python-dotenv). Never commit keys
- **LLM provider swap**: Use `_create_llm()` in `core/translator.py` — dynamic import based on config. RAG engine reuses this same function
- **Audio format**: Always PCM float32, 16kHz mono. Whisper auto-detects language (en/de)
- **Audio chunk size**: 1.0s (configured in `audio.chunk_duration`). Front-end (`AudioCapture.swift`) and back-end (`config.yaml`) must agree. This is the LocalAgreement-2 update period — smaller chunks = faster but more CPU
- **Async in WebSocket handlers**: Use `await chain.ainvoke()` (sync) or `chain.astream()` (流式) for LangChain calls inside FastAPI WebSocket endpoints. Translation uses `astream()` to push tokens to the frontend incrementally
- **Whisper backend**: `core/stt.py` uses `mlx-whisper` (Apple Silicon Metal GPU + ANE) with **fp16** model (not q4 — q4 is much more prone to repetition hallucinations under LocalAgreement-2). Always pass `condition_on_previous_text=False` to reduce hallucinations. Bench backends with `scripts/bench_whisper.py` before switching.
- **Streaming STT (LocalAgreement-2)**: `core/stt_stream.py` `StreamingSTT` is per-AudioSource. Each `feed(audio_chunk)` returns `confirmed_text` (newly stable, increments) + `tentative_text` (current best guess, replaced each call). Words are normalized (lowercase + strip trailing punct) before LCP comparison to tolerate Whisper's punctuation jitter. **Repetition filter**: any word repeating >4 times consecutively triggers truncation (catches "the the the" / "woo woo" Whisper hallucinations).
- **Sentence segmentation**: `SentenceSegmenter` (per-speaker) splits text by punctuation (.?!), not by fixed time chunks. Each AudioSource has its own segmenter with independent pending buffer. Completed sentences are written to SharedHistory.
- **Sentence ID flow**: Each AudioSource has its own `partial_id`. Partial transcript messages reuse this ID so the frontend updates the same row in place. When a sentence completes, the final is pushed synchronously (before new partial), then partial_id is reset. `insert_after` field handles multi-sentence splits.
- **Dual-source concurrency**: Two AudioSources run in parallel via `asyncio.create_task`. `_whisper_lock` (asyncio.Lock) serializes GPU inference (MLX Metal doesn't support concurrent access). SentenceSegmenters are per-speaker so no locking needed. SharedHistory.add_sentence uses list.append (GIL atomic).
- **Known limitation**: Voice Processing (AEC) conflicts with ScreenCaptureKit's audio capture (AUVPAggregate device conflict). Echo cancellation must use alternative approaches (RMS-based suppression or headphones).
- **Mic failure isolation**: `startMicrophoneCapture()` is wrapped in do/catch — mic permission denial or hardware failure doesn't block system audio capture.
- **Suggestion trigger**: Debounce mode — interviewer says a sentence → start N-second timer. New sentence resets timer. Timer expires → generate suggestion using all consecutive interviewer sentences. New suggestion replaces old one. Delay configurable via `conversation.suggestion_debounce` in config.yaml
