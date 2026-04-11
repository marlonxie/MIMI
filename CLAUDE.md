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
Swift App (SwiftUI) ──WebSocket──→ Python Backend (FastAPI)
│                                      │
├── ScreenCaptureKit (系统音频)    ┌────┼─────────────────┐
├── AVAudioEngine (麦克风)        ▼    ▼                 ▼
└── NSPanel (悬浮字幕窗)      core/stt_stream    core/translator   rag/engine
    (1s chunks)              ↓ (LocalAgreement-2)  (LangChain LCEL, (LangChain RAG,
                          core/stt                  Gemini/Claude,   ChromaDB)
                          (mlx-whisper,             .astream())
                           Metal GPU + ANE)               │
                                        ↓
                                core/conversation.py
                                (句子分割 + 对话记录 + 上下文窗口)
```

- **WebSocket message types** (字幕全部按 `sentence_id` 关联):
  - `"type": "transcript"` — 英文识别结果，`is_final` 区分 partial（半透明更新中）/ final（定型）
  - `"type": "translation_delta"` — 中文翻译流式 token 增量
  - `"type": "translation_final"` — 中文翻译完成（完整文本，覆盖 delta 拼接误差）
  - `"type": "suggestion"` — RAG 回答提示（debounce 触发）
- **Streaming STT pipeline**: 前端每 1s 发一块音频。后端每个 speaker 一个 `StreamingSTT` 实例，维护累积音频缓冲，在整个 buffer 上重新跑 Whisper，用 **LocalAgreement-2** 算法（连续两次推理的最长公共前缀）判断哪些词稳定到可以提交。提交的稳定文本喂给 ConversationManager 做分句，未提交的 tentative 文本作为 partial transcript 推送给前端。
- **Conversation manager**: Accumulates confirmed STT results into complete sentences, maintains full history, provides context window to translator and RAG
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
- **Streaming STT (LocalAgreement-2)**: `core/stt_stream.py` `StreamingSTT` is per-speaker. Each `feed(audio_chunk)` returns `confirmed_text` (newly stable, increments) + `tentative_text` (current best guess, replaced each call). Words are normalized (lowercase + strip trailing punct) before LCP comparison to tolerate Whisper's punctuation jitter. **Repetition filter**: any word repeating >4 times consecutively triggers truncation (catches "the the the" / "woo woo" Whisper hallucinations).
- **Sentence segmentation**: ConversationManager splits text by punctuation (.?!), not by fixed time chunks. With LocalAgreement-2 in front, the input it receives has much more reliable punctuation (Whisper's hallucinated mid-buffer periods are filtered out by LCP).
- **Sentence ID flow**: Each in-progress utterance has a `current_partial_id` per speaker. Partial transcript messages reuse this ID so the frontend updates the same row in place. When a sentence completes, the ID is "promoted" to the final message — the frontend transitions the same row from partial-style (opacity 0.5 + cursor ▎) to final-style (opacity 0.9). Next partial gets a new ID.
- **Suggestion trigger**: Debounce mode — interviewer says a sentence → start N-second timer. New sentence resets timer. Timer expires → generate suggestion using all consecutive interviewer sentences. New suggestion replaces old one. Delay configurable via `conversation.suggestion_debounce` in config.yaml
