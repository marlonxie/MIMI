"""对话管理器 — 分句、对话记录、上下文窗口、触发检测"""

import json
import time
from datetime import datetime
from pathlib import Path


class ConversationManager:
    """管理面试对话的完整生命周期"""

    SENTENCE_ENDINGS = {'.', '?', '!', '。', '？', '！'}

    def __init__(self, context_window_size: int = 10, export_path: str = "./transcripts"):
        self.context_window_size = context_window_size
        self.export_path = Path(export_path)
        self.history: list[dict] = []  # 完整对话记录
        self.pending_text = ""  # 未完成的句子碎片
        self.pending_speaker = None
        self.pending_language = None
        self.pending_start_time = None
        self.start_time = time.time()

    def add_transcription(self, stt_result: dict, speaker: str) -> list[dict]:
        """
        接收 STT 结果，返回已完成的句子列表。

        利用 Whisper segments 的标点判断句子是否完整：
        - 以 .?! 结尾 → 完整，输出
        - 否则 → 暂存到 pending_text，等下一个 chunk

        Args:
            stt_result: {"text": str, "language": str, "segments": [...]}
            speaker: "interviewer" 或 "me"

        Returns:
            完成的句子列表 [{"speaker", "text", "language", "timestamp"}]
        """
        text = stt_result.get("text", "").strip()
        language = stt_result.get("language", "unknown")

        if not text:
            return []

        completed = []

        # 如果 speaker 变了，先把 pending 强制输出
        if self.pending_text and self.pending_speaker != speaker:
            completed.append(self._flush_pending())

        # 处理当前文本
        if self.pending_text:
            text = self.pending_text + " " + text
            self.pending_text = ""
        else:
            self.pending_start_time = time.time()

        # 按句子边界切分
        current_sentence = ""
        for char in text:
            current_sentence += char
            if char in self.SENTENCE_ENDINGS:
                sentence = current_sentence.strip()
                if sentence:
                    entry = self._create_entry(speaker, sentence, language)
                    self.history.append(entry)
                    completed.append(entry)
                current_sentence = ""

        # 剩余部分存入 pending
        remaining = current_sentence.strip()
        if remaining:
            # 安全阀：pending 超过 15 秒强制输出
            if (self.pending_start_time and
                    time.time() - self.pending_start_time > 15):
                entry = self._create_entry(speaker, remaining, language)
                self.history.append(entry)
                completed.append(entry)
                self.pending_text = ""
                self.pending_start_time = None
            else:
                self.pending_text = remaining
                self.pending_speaker = speaker
                self.pending_language = language
                if self.pending_start_time is None:
                    self.pending_start_time = time.time()

        return completed

    def flush(self) -> list[dict]:
        """强制输出所有 pending 文本（面试结束时调用）"""
        if self.pending_text:
            return [self._flush_pending()]
        return []

    def get_context_window(self, n: int = None) -> str:
        """
        返回最近 n 句对话，格式化为 LLM 可读的上下文。

        Returns:
            "[Interviewer] Tell me about your ML experience.\n[Me] I worked on..."
        """
        if n is None:
            n = self.context_window_size

        recent = self.history[-n:] if len(self.history) > n else self.history

        lines = []
        for entry in recent:
            label = "Interviewer" if entry["speaker"] == "interviewer" else "Me"
            lines.append(f"[{label}] {entry['text']}")

        return "\n".join(lines)

    def has_new_interviewer_speech(self, since_index: int) -> bool:
        """检查从 since_index 之后是否有新的面试官发言"""
        for entry in self.history[since_index:]:
            if entry["speaker"] == "interviewer":
                return True
        return False

    def get_last_interviewer_text(self) -> str:
        """获取面试官最近说的完整内容（可能跨多句）"""
        texts = []
        for entry in reversed(self.history):
            if entry["speaker"] == "interviewer":
                texts.insert(0, entry["text"])
            else:
                break  # 遇到自己说的就停
        return " ".join(texts)

    def export_transcript(self, filename: str = None) -> str:
        """导出完整对话记录到文件"""
        self.export_path.mkdir(parents=True, exist_ok=True)
        if filename is None:
            filename = f"interview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        filepath = self.export_path / filename
        data = {
            "date": datetime.now().isoformat(),
            "duration_seconds": time.time() - self.start_time,
            "turns": len(self.history),
            "history": self.history,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return str(filepath)

    def current_timestamp(self) -> str:
        """返回 hh:mm:ss 格式的当前会话时长，用于 partial transcript 的 timestamp 字段"""
        elapsed = time.time() - self.start_time
        minutes, seconds = divmod(int(elapsed), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _create_entry(self, speaker: str, text: str, language: str) -> dict:
        return {
            "speaker": speaker,
            "text": text,
            "language": language,
            "timestamp": self.current_timestamp(),
        }

    def _flush_pending(self) -> dict:
        entry = self._create_entry(
            self.pending_speaker or "unknown",
            self.pending_text,
            self.pending_language or "unknown",
        )
        self.history.append(entry)
        self.pending_text = ""
        self.pending_speaker = None
        self.pending_language = None
        self.pending_start_time = None
        return entry
