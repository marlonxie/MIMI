"""对话管理 — SharedHistory（共享对话记录）+ SentenceSegmenter（per-speaker 分句器）

拆分原因：两路音频（系统音频 + 麦克风）并发处理时，pending 状态必须独立，
但 history 需要共享（翻译 context 要看双方对话）。
"""

import json
import time
from datetime import datetime
from pathlib import Path


class SharedHistory:
    """共享的对话历史。两路音频的 SentenceSegmenter 都往这里写完成的句子。

    只负责：history 存储、context_window 查询、导出。
    不持有 pending 状态（那是 SentenceSegmenter 的事）。
    """

    def __init__(self, context_window_size: int = 10, export_path: str = "./transcripts"):
        self.context_window_size = context_window_size
        self.export_path = Path(export_path)
        self.history: list[dict] = []  # 双路交织的完整对话记录
        self.start_time = time.time()

    def add_sentence(self, speaker: str, text: str, language: str) -> dict:
        """添加一个完成的句子到 history。返回 entry dict。"""
        entry = {
            "speaker": speaker,
            "text": text,
            "language": language,
            "timestamp": self.current_timestamp(),
        }
        self.history.append(entry)
        return entry

    def get_context_window(self, n: int = None) -> str:
        """返回最近 n 句对话，格式化为 LLM 可读的上下文。

        Returns:
            "[Interviewer] Tell me about your ML experience.\\n[Me] I worked on..."
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
                break
        return " ".join(texts)

    def current_timestamp(self) -> str:
        """返回 hh:mm:ss 格式的当前会话时长"""
        elapsed = time.time() - self.start_time
        minutes, seconds = divmod(int(elapsed), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

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


class SentenceSegmenter:
    """per-speaker 的分句器。持有 pending 缓冲状态，完成的句子写入 SharedHistory。

    每个 AudioSource 持有一个独立的 SentenceSegmenter 实例，
    两路不会互相覆盖 pending 状态。
    """

    SENTENCE_ENDINGS = {'.', '?', '!', '。', '？', '！'}
    PENDING_TIMEOUT = 15.0  # pending 超过此秒数强制输出（异常保护）
    PAUSE_THRESHOLD = 0.5   # 词间停顿超过此值视为句子边界（基于测试数据：97% 停顿处离线有标点）

    def __init__(self, speaker: str, shared_history: SharedHistory):
        self.speaker = speaker
        self.shared_history = shared_history
        self.pending_text = ""  # 用于外部观察（preview 推送）
        self.pending_language = None
        self.pending_start_time = None
        self._pending_words: list[dict] = []  # word 对象列表，带时间戳

    def add_text(self, text: str, language: str) -> list[dict]:
        """接收 confirmed 文本，按标点分句。完成的句子写入 shared_history。

        Returns:
            完成的句子列表 [{"speaker", "text", "language", "timestamp"}]
        """
        text = text.strip()
        if not text:
            return []

        completed = []

        # 拼接 pending
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
                    entry = self.shared_history.add_sentence(self.speaker, sentence, language)
                    completed.append(entry)
                current_sentence = ""

        # 剩余部分存入 pending
        remaining = current_sentence.strip()
        if remaining:
            if (self.pending_start_time and
                    time.time() - self.pending_start_time > self.PENDING_TIMEOUT):
                entry = self.shared_history.add_sentence(self.speaker, remaining, language)
                completed.append(entry)
                self.pending_text = ""
                self.pending_start_time = None
            else:
                self.pending_text = remaining
                self.pending_language = language
                if self.pending_start_time is None:
                    self.pending_start_time = time.time()

        return completed

    def add_words(self, words: list[dict], language: str) -> list[dict]:
        """接收 confirmed words（带时间戳），按标点 + 词间停顿分句。

        和 add_text() 的区别：利用 word 级时间戳在停顿处切分，不仅靠 Whisper 的标点。
        基于测试数据，离线 Whisper 在词间停顿 >0.5s 处 97% 有标点，所以停顿是
        最可靠的自然边界信号。

        Args:
            words: [{"word": str, "start": float, "end": float}, ...]
            language: str

        Returns:
            完成的句子列表 [{"speaker", "text", "language", "timestamp"}]
        """
        if not words:
            return []

        completed = []

        # 拼接上次 pending 和新 words
        all_words = self._pending_words + words

        sentence_words: list[dict] = []
        for i, w in enumerate(all_words):
            sentence_words.append(w)
            word_str = w["word"].strip()

            # 句末标点？
            is_sentence_end = bool(word_str) and word_str[-1] in self.SENTENCE_ENDINGS

            # 词间停顿？（不是最后一个词才能判断）
            is_pause = False
            if i < len(all_words) - 1:
                gap = all_words[i + 1]["start"] - w["end"]
                if gap > self.PAUSE_THRESHOLD:
                    is_pause = True

            if is_sentence_end or is_pause:
                text = "".join(sw["word"] for sw in sentence_words).strip()
                # 停顿切但末尾没标点 → 补句号（让翻译知道这是完整句子）
                if is_pause and not is_sentence_end and text and text[-1] not in ".,!?;:":
                    text += "."
                if text:
                    entry = self.shared_history.add_sentence(self.speaker, text, language)
                    completed.append(entry)
                sentence_words = []

        # 剩余的 words 进 pending
        self._pending_words = sentence_words
        self.pending_text = "".join(w["word"] for w in sentence_words).strip()
        if sentence_words:
            self.pending_language = language
            if self.pending_start_time is None:
                self.pending_start_time = time.time()
            # 异常保护：pending 超时强制输出
            elif time.time() - self.pending_start_time > self.PENDING_TIMEOUT:
                text = self.pending_text
                if text and text[-1] not in ".,!?;:":
                    text += "."
                entry = self.shared_history.add_sentence(self.speaker, text, language)
                completed.append(entry)
                self._pending_words = []
                self.pending_text = ""
                self.pending_start_time = None
        else:
            self.pending_start_time = None

        return completed

    def flush(self) -> list[dict]:
        """强制输出 pending 文本。面试结束 / 停止录音时调用。"""
        # 优先从 _pending_words 取（add_words 路径），否则用 pending_text（add_text 兼容）
        if self._pending_words:
            text = "".join(w["word"] for w in self._pending_words).strip()
        elif self.pending_text:
            text = self.pending_text
        else:
            return []

        # flush 时末尾没标点的话补句号
        if text and text[-1] not in ".,!?;:":
            text += "."

        entry = self.shared_history.add_sentence(
            self.speaker,
            text,
            self.pending_language or "unknown",
        )
        self._pending_words = []
        self.pending_text = ""
        self.pending_language = None
        self.pending_start_time = None
        return [entry]
