# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MIMI 面试助手 — macOS interview assistant for Mandarin native speakers doing English/German interviews. Mixed architecture: Python backend (FastAPI + WebSocket) + Swift native frontend (planned).

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
/Users/marlon/anaconda3/envs/mimi/bin/python tests/test_translator.py
/Users/marlon/anaconda3/envs/mimi/bin/python tests/test_rag.py
/Users/marlon/anaconda3/envs/mimi/bin/python tests/test_websocket.py  # requires server running
```

**Install packages:**
```bash
/Users/marlon/anaconda3/envs/mimi/bin/pip install <package>
```

## Architecture

```
Swift App (planned) ──WebSocket──→ Python Backend (FastAPI)
                                      │
                          ┌───────────┼───────────────┐
                          ▼           ▼               ▼
                     core/stt.py  core/translator.py  rag/engine.py
                     (Whisper,    (LangChain LCEL,    (LangChain RAG,
                      local)      Gemini/Claude)      ChromaDB + embeddings)
                                      │
                              core/conversation.py
                              (句子分割 + 对话记录 + 上下文窗口)
```

- **Two WebSocket message types**: `"type": "translation"` (every sentence, realtime) and `"type": "suggestion"` (after interviewer finishes speaking, with RAG answer hints)
- **Conversation manager**: Accumulates STT results into complete sentences, maintains full history, provides context window to translator and RAG
- **Config-driven**: All settings in `mimi-backend/config.yaml`. Switch LLM provider by changing `translator.provider` ("gemini"/"claude")
- **RAG output format**: 📌 Question understanding (Chinese) + 💡 Key points (Chinese) + 🗣️ Example answer (in interview language en/de)

## Key Conventions

- **LangChain v1 required**: Always reference LangChain v1 docs/source before writing LangChain code. Current: langchain-core 1.2.21. Use LCEL pipe syntax (`prompt | llm | parser`), `.invoke()` / `.ainvoke()`
- **Environment variables**: API keys in `mimi-backend/.env` (loaded via python-dotenv). Never commit keys
- **LLM provider swap**: Use `_create_llm()` in `core/translator.py` — dynamic import based on config. RAG engine reuses this same function
- **Audio format**: Always PCM float32, 16kHz mono. Whisper auto-detects language (en/de)
- **Async in WebSocket handlers**: Use `await chain.ainvoke()` for LangChain calls inside FastAPI WebSocket endpoints
- **Sentence segmentation**: ConversationManager splits text by punctuation (.?!), not by fixed time chunks. Pending text is buffered until sentence completes
- **Suggestion trigger**: Fires when `speaker == "interviewer"` and last history entry is also from interviewer (speaker change detection)
