# MIMI 面试助手 — 开发计划

> macOS 面试助手，帮助中文母语者应对英语/德语面试
> 架构：Swift 原生前端 + Python AI 后端，通过 WebSocket 通信

---

## 当前进度

| 阶段 | 状态 | 说明 |
|------|------|------|
| 阶段 0：环境准备 | ✅ 完成 | brew 依赖、项目骨架、git init |
| 阶段 1：Python 后端核心 | ✅ 完成 | server.py + stt.py + translator.py（LangChain + Gemini） |
| 阶段 2：对话管理 + RAG 问答 | ✅ 完成 | 对话管理器 + 文档索引 + RAG 提示生成 |
| 阶段 3：Swift 前端 | ✅ 完成 | MenuBarExtra + NSPanel 悬浮窗 + ScreenCaptureKit + AVAudioEngine |
| 阶段 4：打磨 | 🔧 进行中 | WebSocket 断连修复、Info.plist 配置、UI 优化 |
| 阶段 5：流式字幕重构 | ✅ 完成 | mlx-whisper GPU+ANE + LocalAgreement-2 + 翻译流式 + 解耦中英文 |

---

## 阶段 0：环境准备 ✅

- [x] `brew install ffmpeg portaudio`
- [x] 项目目录结构创建
- [x] `git init`
- [x] `.gitignore` + `.env`（API keys）
- [x] `config.yaml` 全局配置

---

## 阶段 1：Python 后端核心 ✅

### 1.1 FastAPI + WebSocket 服务 ✅
- **文件**: `mimi-backend/server.py`
- WebSocket 端点 `/ws`，接收音频（binary）和控制消息（JSON）

### 1.2 Whisper STT ✅
- **文件**: `mimi-backend/core/stt.py`
- 本地 Whisper small 模型，自动检测英语/德语

### 1.3 LangChain 翻译 ✅
- **文件**: `mimi-backend/core/translator.py`
- LCEL chain，支持 Gemini/Claude 切换，带对话上下文

### 1.4 测试 ✅
- `tests/test_stt.py` — Whisper 模型加载 + 静音 + 音频文件转写
- `tests/test_translator.py` — 英/德→中翻译 + 异步翻译
- `tests/test_websocket.py` — WebSocket 连接 + 真实音频端到端

---

## 阶段 2：对话管理 + RAG 问答 ✅

### 2.1 对话管理器 ✅
- **文件**: `mimi-backend/core/conversation.py`
- 利用 Whisper segments 标点分句（不固定 3 秒切割）
- 完整对话记录，面试后可导出 JSON 回顾
- 上下文窗口（最近 N 句）给翻译和 RAG 使用
- `has_new_interviewer_speech()` 检查新面试官发言

### 2.2 文档索引 ✅
- **文件**: `mimi-backend/rag/indexer.py`
- LangChain document loaders 解析 PDF/MD/TXT
- RecursiveCharacterTextSplitter 切片
- HuggingFaceEmbeddings（all-MiniLM-L6-v2，本地 22MB）
- ChromaDB 存储，全量重建
- 运行：`python -m rag.indexer`

### 2.3 RAG 引擎 ✅
- **文件**: `mimi-backend/rag/engine.py`
- LCEL chain：retriever | format_docs → prompt → LLM → parser
- 输出格式：📌 问题理解（中文）+ 💡 回答要点（中文）+ 🗣️ 示例回答（面试语言）
- 复用 translator.py 的 `_create_llm()` 模式

### 2.4 server.py 集成 ✅
- 两种 WebSocket 消息类型：`"type": "translation"` + `"type": "suggestion"`
- 翻译区每句话实时更新，提示区 debounce 触发（面试官最后一句后 N 秒无新句子才生成，新提示覆盖旧提示）
- RAG 引擎可选加载（无索引时自动跳过）
- 断开连接时自动导出对话记录

### 2.5 测试 ✅
- `tests/test_rag.py` — 对话管理 + 索引 + 检索 + 提示生成 + 上下文翻译

---

## 阶段 3：Swift 前端 ✅

> 环境：macOS 26.3 + Xcode 26.3 + Swift 6.2

### 3.1 SwiftUI macOS App ✅
- **文件**: `mimi-app/MimiApp/MimiApp.swift`
- MenuBarExtra 菜单栏图标 + AppDelegate 管理 NSPanel 悬浮窗
- @Observable AppState 驱动 UI 自动更新

### 3.2 悬浮字幕窗口 ✅
- **文件**: `mimi-app/MimiApp/OverlayWindow.swift`
- NSPanel 半透明、置顶、可拖拽
- VSplitView：翻译区（上）+ 回答提示区（下），独立滚动

### 3.3 音频捕获 ✅
- **文件**: `mimi-app/MimiApp/AudioCapture.swift`
- `ScreenCaptureKit` 捕获系统音频（面试官）→ 48kHz 降采样到 16kHz
- `AVAudioEngine` 捕获麦克风（自己）→ AVAudioConverter 转 16kHz mono
- 两路音频各自缓冲 3 秒后发送

### 3.4 WebSocket 客户端 ✅
- **文件**: `mimi-app/MimiApp/WebSocketClient.swift`
- URLSessionWebSocketTask 连接 `ws://127.0.0.1:8765/ws`
- 发送：binary（音频）+ string（JSON 控制命令）
- 接收：translation / suggestion 消息 → 通过回调更新 AppState
- 指数退避自动重连（最多 10 次）

### 3.5 端到端测试 ✅
- 播放 YouTube 面试视频 → 翻译区实时字幕 + 提示区答案建议 → 已验证

---

## 阶段 4：打磨 🔧

- [ ] 修复 Info.plist 警告（Xcode Copy Bundle Resources 重复）
- [ ] 修复 WebSocket 断连后重连稳定性
- [ ] 麦克风权限未弹窗（需确认 Info.plist 生效）
- [ ] 快捷键启动/停止录音
- [ ] 一键启动脚本（Python 后端 + Swift 前端）
- [ ] UI 美化（字体、颜色、动画过渡）
- [ ] 配置界面（语言、Whisper 模型大小、LLM provider）

---

## 阶段 5：流式字幕重构 ✅

> 起因：原方案 3s chunk + 等句子完成 + 等翻译完成才一起出，首字延迟 5–10s，且 Whisper 在 chunk 边界乱加标点导致句子被错切

### 5.1 解耦中英文 + 翻译流式 ✅
- **后端**: `core/translator.py` 加 `translate_stream()` 用 `chain.astream()`
- **后端**: `server.py` 把 `_send_translation` 重写为 `_send_transcript_and_translate`：先推 transcript（立即），再流式推 translation_delta，最后推 translation_final
- **前端**: `Models.swift` `TranslationEntry` 从 struct 改成 `@Observable class`，按 `sentenceId` 索引；新 3 类消息 `TranscriptMessage` / `TranslationDeltaMessage` / `TranslationFinalMessage`
- **前端**: `MimiApp.swift` AppState 三个新回调按 ID 查/创建/更新 entry，delta 追加，final 用完整文本覆盖防拼接误差
- **前端**: `OverlayWindow.swift` `TranslationRow` 改 `@Bindable`，partial 半透明 + 末尾光标 ▎，完成后淡入定型

### 5.2 STT 真正流式（LocalAgreement-2 + GPU/ANE）✅
- **Benchmark**: `scripts/bench_whisper.py` 对比 openai/whisper CPU vs mlx-whisper Metal vs faster-whisper CPU。结果 mlx-whisper 比 openai 快 6.6×，比 faster-whisper 快 4.5×
- **STT 后端**: `core/stt.py` 切到 mlx-whisper（**fp16** 模型，q4 量化版幻觉太多）+ `condition_on_previous_text=False`
- **流式包装**: `core/stt_stream.py` 新文件 ~200 行实现 LocalAgreement-2：
  - 维护累积音频缓冲（≤25s 安全阀）
  - 每次 feed 在整个 buffer 上重新跑 Whisper
  - LCP 算法对比两次 hypothesis 的最长公共前缀（词级，规范化后比较）
  - 提交稳定前缀，截掉对应音频，剩余作 tentative
  - **重复幻觉过滤**：连续 >4 次同一个词触发截断，砍掉 "the the the" / "woo woo" 类幻觉
- **server.py 接入**: 每个 speaker 独立 `StreamingSTT` 实例 + `current_partial_id`（让 partial → final 在前端原地更新同一行）
- **chunk 改 1s**: `config.yaml` `audio.chunk_duration: 1.0` + `AudioCapture.swift` `chunkDuration: 1.0`
- **测试**: `tests/test_stt_stream.py`（流式拼接结果与离线基线 0.91× 字数比例，单元测试 + 集成测试）+ `tests/test_translator_stream.py`（流式 token 产出验证）

### 5.3 性能数据
| 指标 | 旧 | 新 |
|---|---|---|
| Whisper 推理（small, 30s 音频） | 10.21s (CPU) | 1.54s (Metal GPU) |
| 首字延迟（理论） | 5–10s | ~2s |
| 中文翻译呈现 | 1.5s 块状一次性 | TTFT ~300ms 后流式 |
| chunk_duration | 3.0s | 1.0s |

---

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| STT | mlx-whisper (GPU+ANE) | small fp16 模型，Metal GPU + Apple Neural Engine，6.6× CPU 速度 |
| 流式 STT | core/stt_stream.py | LocalAgreement-2 算法，1s 更新周期，词级 LCP + 重复幻觉过滤 |
| 翻译 | LangChain + Gemini | LCEL chain `.astream()`，带对话上下文，可切换 Claude |
| 对话管理 | conversation.py | 分句 + 记录 + 上下文窗口 |
| RAG | LangChain + ChromaDB | 本地 embedding + 检索 + 提示生成 |
| 后端 | FastAPI + WebSocket | uvicorn, 异步 |
| 前端 | Swift + SwiftUI | MenuBarExtra + NSPanel 悬浮窗 + ScreenCaptureKit + AVAudioEngine |
| 通信 | WebSocket | binary(音频) + JSON(transcript/translation_delta/translation_final/suggestion) |
