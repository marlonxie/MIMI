"""per-speaker 分句器。持有 pending 缓冲状态，完成的句子写入 SharedHistory。"""

import time

from conversation.history import SharedHistory


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
        self.pending_language = None
        self.pending_start_time = None
        self._pending_words: list[dict] = []  # word 对象列表，带时间戳

    @property
    def pending_text(self) -> str:
        """从 _pending_words 派生的字符串（用于外部 preview 推送）。

        永远和 _pending_words 一致，消除双写漂移风险。
        """
        return "".join(w["word"] for w in self._pending_words).strip()

    def add_words(self, words: list[dict], language: str) -> list[dict]:
        """接收 confirmed words（带时间戳），按标点 + 词间停顿分句。

        利用 word 级时间戳在停顿处切分，不仅靠 Whisper 的标点。
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
                self.pending_start_time = None
        else:
            self.pending_start_time = None

        return completed

    def flush(self) -> list[dict]:
        """强制输出 pending 文本。面试结束 / 停止录音时调用。"""
        if not self._pending_words:
            return []

        text = self.pending_text
        # flush 时末尾没标点的话补句号
        if text and text[-1] not in ".,!?;:":
            text += "."

        entry = self.shared_history.add_sentence(
            self.speaker,
            text,
            self.pending_language or "unknown",
        )
        self._pending_words = []
        self.pending_language = None
        self.pending_start_time = None
        return [entry]
