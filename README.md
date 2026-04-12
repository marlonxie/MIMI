# MIMI 面试助手

Real-time interview assistant for Mandarin speakers doing English/German interviews. Captures system audio + microphone, transcribes with streaming Whisper, translates live to Chinese, and optionally generates answer suggestions via RAG.

## What It Does

- **Live transcription** — Captures interviewer (system audio) and your voice (microphone) separately via ScreenCaptureKit
- **Streaming subtitles** — Words appear as they're spoken using LocalAgreement-2 algorithm, ~2s latency
- **Real-time translation** — Streams Chinese translation token-by-token as sentences complete
- **Answer suggestions** (optional) — RAG-powered hints based on your resume/prep docs, triggered after interviewer pauses
- **Floating overlay** — Transparent always-on-top subtitle window that sits over any video call app

## Architecture

```
Swift App (SwiftUI)  ──WebSocket──→  Python Backend (FastAPI)
│                                         │
├─ ScreenCaptureKit (system audio)   ├─ stt_stream.py (LocalAgreement-2)
├─ AVAudioEngine (microphone)        ├─ stt.py (mlx-whisper, Metal GPU)
└─ NSPanel (floating overlay)        ├─ translator.py (Gemini/Claude, streaming)
                                     ├─ conversation.py (sentence segmentation)
                                     └─ rag/ (LangChain + ChromaDB)
```

**Frontend**: Native macOS app in Swift/SwiftUI. Captures audio in 1s PCM chunks, sends over WebSocket, renders streaming subtitles with partial/final states.

**Backend**: Python FastAPI WebSocket server. Each audio chunk feeds into a cumulative buffer; Whisper runs on the full buffer each time, and LocalAgreement-2 extracts stable words by comparing consecutive inferences. Stable text flows through sentence segmentation → LLM translation (streamed) → optional RAG suggestion.

## Tech Stack

| Layer | Tech |
|-------|------|
| Audio capture | ScreenCaptureKit + AVAudioEngine |
| Speech-to-text | mlx-whisper (Apple Silicon Metal GPU + ANE) |
| Streaming STT | LocalAgreement-2 (consecutive-inference LCP) |
| Translation | LangChain LCEL → Gemini Flash / Claude Sonnet |
| RAG | LangChain + ChromaDB + all-MiniLM-L6-v2 |
| Frontend | SwiftUI + NSPanel overlay |
| Transport | WebSocket (JSON messages) |

## Requirements

- macOS 14+ on Apple Silicon (M1/M2/M3)
- Python 3.11+ (conda recommended)
- Xcode 16+
- API key for Gemini or Claude

## Setup

```bash
# 1. Clone
git clone https://github.com/marlonxie/MIMI.git
cd MIMI

# 2. Python environment
conda create -n mimi python=3.11
conda activate mimi
pip install -r mimi-backend/requirements.txt  # mlx-whisper, fastapi, langchain, etc.

# 3. Environment variables
cp mimi-backend/.env.example mimi-backend/.env
# Edit .env with your API keys

# 4. Start backend
cd mimi-backend && python server.py
# WebSocket server on ws://127.0.0.1:8765

# 5. Build & run the Swift app in Xcode
open mimi-app/MimiApp.xcodeproj
# Grant microphone + screen recording permissions when prompted
```

## Configuration

All settings in [`mimi-backend/config.yaml`](mimi-backend/config.yaml):

- `stt.model_size` — Whisper model (tiny/base/small/medium/large)
- `translator.provider` — "gemini" or "claude"
- `conversation.enable_suggestion` — Toggle RAG answer hints
- `conversation.suggestion_debounce` — Seconds to wait after interviewer stops before generating suggestion

## License

MIT
