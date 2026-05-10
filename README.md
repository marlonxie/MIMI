# MIMI 面试助手

Real-time interview assistant for Mandarin speakers doing English/German interviews. Captures system audio + microphone, transcribes with streaming Whisper, translates live to the native language, and optionally generates answer suggestions via RAG.

## What It Does

- **Live transcription** — Separates interviewer (system audio) from your voice (microphone) via ScreenCaptureKit
- **Streaming subtitles** — Words appear as they're spoken using LocalAgreement-2, ~2s latency
- **Real-time translation** — Streams translation token-by-token (interview language → your native language)
- **Smart answer suggestions** — Three-layer trigger (local filter → intent LLM → RAG) automatically detects real questions and skips fillers; manual override via clickable subtitle
- **Bilingual output** — Suggestions rendered in 3 sections: 📌 question understanding (native) + 💡 key points (bilingual) + 🗣️ sample answer (interview language, STAR style with metrics)
- **Runtime controls** — Floating overlay with mic + screen-recording toggles; menu bar; Cmd+, Settings panel for language + RAG toggles
- **Floating overlay** — Transparent always-on-top subtitle window that sits over any video call app
- **Speaker-safe** — Uses Apple's native `VoiceProcessingIO` AEC so interviewer audio played through the speaker is cancelled from the mic track; works without headphones, no virtual audio driver needed

## Architecture

```
Swift App (SwiftUI) ──WebSocket (binary PCM + JSON)──→ Python Backend (FastAPI)
│                                                              │
├─ ScreenCaptureKit (system audio, prefix 0x00)       ┌────────┴────────┐
├─ AVAudioEngine  (microphone,    prefix 0x01)        │                 │
├─ NSPanel (floating overlay, auto level-swap)        ▼                 ▼
└─ Settings scene (Cmd+,)                     AudioSource          AudioSource
                                              (interviewer)        (me)
                                              ├─ StreamingSTT      ├─ StreamingSTT
                                              ├─ SentenceSegmenter ├─ SentenceSegmenter
                                              └─ partial_id        └─ partial_id
                                                         ↓                ↓
                                                      SharedHistory (shared)
                                                      │
                                                      ├──→ translator (streaming)
                                                      │
                                                      └──→ RAG suggestion pipeline:
                                                            [A] question_filter
                                                            [B] intent_classifier (LLM gate)
                                                            [C] rag/engine.py
                                                            manual path: bypasses A/B
```

**Frontend**: Native macOS app in Swift/SwiftUI. Captures system audio and microphone independently in 1s PCM chunks (each tagged with a 1-byte source prefix), sends over WebSocket, renders streaming subtitles with partial/final states. `NSPanel` overlay auto-drops to `.normal` level when another window becomes key (so the Settings window isn't blocked by the floating subtitle).

**Backend**: Python FastAPI WebSocket server. Each audio source (interviewer/me) has an independent `AudioSource` pipeline running in its own coroutine. Audio chunks feed a cumulative buffer; Whisper (mlx-whisper on Metal GPU) runs on the full buffer each time, and LocalAgreement-2 extracts stable words by comparing consecutive inferences. Stable text flows through per-speaker sentence segmentation → shared history → streamed LLM translation → optional RAG answer pipeline.

**Suggestion trigger** (three layers, all bypassed by manual click):

| Layer | Cost | Filters |
|---|---|---|
| `conversation/question_filter.py` | O(1), local | Length < 3 words / pure punctuation / bilingual filler blacklist ("OK", "Got it", "Ja", ...) |
| `conversation/intent_classifier.py` | ~300ms Gemini flash | Semantic non-questions ("So our team uses Python", "Let me think") |
| `rag/engine.py` | ~2s Gemini flash + ChromaDB | Retrieval + bilingual tri-section answer generation |

Manual override: click an interviewer subtitle row → 💡 icon appears → click to trigger RAG directly on that sentence with 5 lines of focused context. Manual always preempts an in-flight auto task.

## Tech Stack

| Layer | Tech |
|-------|------|
| Audio capture | ScreenCaptureKit + AVAudioEngine |
| Echo cancellation | Apple `VoiceProcessingIO` (hardware AEC + NS + AGC, no extra deps) |
| Audio pipeline | AudioSource (per-speaker: StreamingSTT + SentenceSegmenter) |
| Speech-to-text | mlx-whisper fp16 (Apple Silicon Metal GPU + ANE) |
| Streaming STT | LocalAgreement-2 (consecutive-inference LCP) |
| Conversation | SharedHistory (shared) + SentenceSegmenter (per-speaker) |
| Translation | LangChain LCEL → Ollama Qwen3-4B-Instruct-2507 (default) / Gemini Flash / Claude Sonnet, streamed |
| RAG | LangChain + ChromaDB + all-MiniLM-L6-v2 embeddings |
| Question gate | Gemini flash yes/no classifier |
| Frontend | SwiftUI + NSPanel overlay + Settings scene |
| Transport | WebSocket (binary audio + JSON control messages) |

## Requirements

- macOS 14+ on Apple Silicon (M1/M2/M3)
- Python 3.11+ (conda recommended)
- Xcode 16+
- **One** LLM backend:
  - **Local (default, recommended)** — Ollama daemon + Qwen3-4B-Instruct-2507 (zero API cost, offline, Apache 2.0)
  - Or cloud — Gemini / Claude API key

## Setup

```bash
# 1. Clone
git clone https://github.com/marlonxie/MIMI.git
cd MIMI

# 2. Python environment
conda create -n mimi python=3.11
conda activate mimi
pip install -r mimi-backend/requirements.txt
```

### LLM backend (pick one)

**Option A — Local Ollama (default, no API key needed)**

```bash
brew install ollama
brew services start ollama
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

Skip the `.env` step below. MIMI auto-detects "no API key" and falls back to local Ollama. TTFT ~100ms, vs Gemini's ~1500ms (network RTT included).

**Option B — Cloud (Gemini / Claude)**

```bash
cp mimi-backend/.env.example mimi-backend/.env
# Edit .env to set GOOGLE_API_KEY or ANTHROPIC_API_KEY
```

Or skip `.env` and set the key in the Settings UI (Cmd+,) at runtime — keys are stored in macOS Keychain.

### Continue setup

```bash
# 3. (Optional) Drop your resume / prep docs into resources/ and index for RAG
mkdir -p resources
# ...add your .md / .pdf / .txt files...
cd mimi-backend && python -m rag.indexer

# 4. Start backend
python server.py
# WebSocket on ws://127.0.0.1:8765

# 5. Build & run the Swift app
open ../mimi-app/MimiApp.xcodeproj
# Grant microphone + screen recording permissions when prompted
```

## Configuration

All settings in [`mimi-backend/config.yaml`](mimi-backend/config.yaml). Key fields:

```yaml
user:
  interview_language: "en"    # STT + translation source (en / de)
  native_language: "zh"       # translation target (zh / en)

stt:
  model_size: "small"         # tiny / base / small / medium / large

translator:
  provider: "gemini"          # "gemini" / "claude" / "ollama"; if cloud provider has no key, auto-falls back to ollama
  model: "gemini-2.5-flash"

conversation:
  enable_suggestion: false    # auto RAG trigger (manual always works)
  suggestion_debounce: 1.5    # short debounce so consecutive sentences merge
  intent_gate: true           # LLM yes/no gate between filter and RAG

audio:
  sample_rate: 16000
  chunk_duration: 1.0         # seconds per STT update cycle
```

Runtime-mutable via the Swift Settings panel (Cmd+,): `interview_language`, `native_language`, `enable_suggestion`. Changes push to the backend over WebSocket without reconnecting.

## Troubleshooting

### System audio captions stop appearing (mic still works)

**Symptom**: Interviewer-side subtitles disappear or never show, but your own voice (microphone) still gets transcribed normally. Backend logs show `interviewer peak ~0.015` regardless of how loud the audio is playing.

**Cause**: Known macOS 26 (Tahoe) CoreAudio bug. Some client process pollutes shared HAL state, after which all subsequent audio captures (ScreenCaptureKit, AVAudioEngine taps) return ~30 dB attenuated audio. Confirmed by Rogue Amoeba (Audio Hijack developers); not a MIMI issue.

**Fix**:

```bash
# 1. Quit Xcode first (Xcode + CoreSimulator are top polluting clients)
# 2. Run the recovery script (will ask for sudo password)
bash mimi-backend/scripts/fix_audio.sh
# 3. Restart backend + MimiApp
```

The script kills CoreAudio clients in the right order then restarts the audio daemons (`killall coreaudiod` alone doesn't work — surviving clients re-pollute within ~1s). Effect lasts 30-60 min.

**Lighter alternative** (~30 sec of clean capture): Option-click menu bar volume icon, switch output device, switch back. Bounces HAL state without killing processes.

**Permanent**: Reboot, or wait for Apple to ship the actual fix.

References:
- [Rogue Amoeba: macOS 26 audio bugs (Nov 2025)](https://weblog.rogueamoeba.com/2025/11/04/macos-26-tahoe-includes-important-audio-related-bug-fixes/)
- [metrovoc fixaudio.sh gist](https://gist.github.com/metrovoc/0b5e3590c6069cf99b01559863bc2ce4)

## License

MIT
