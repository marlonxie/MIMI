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

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| STT | Whisper (本地) | openai-whisper, small 模型 |
| 翻译 | LangChain + Gemini | LCEL chain，带对话上下文，可切换 Claude |
| 对话管理 | conversation.py | 分句 + 记录 + 上下文窗口 |
| RAG | LangChain + ChromaDB | 本地 embedding + 检索 + 提示生成 |
| 后端 | FastAPI + WebSocket | uvicorn, 异步 |
| 前端 | Swift + SwiftUI | MenuBarExtra + NSPanel 悬浮窗 + ScreenCaptureKit + AVAudioEngine |
| 通信 | WebSocket | binary(音频) + JSON(translation/suggestion) |
