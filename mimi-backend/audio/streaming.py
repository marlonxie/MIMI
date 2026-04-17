"""LocalAgreement-2 流式 STT 包装器。

参考: Macháček et al. 2023, "Turning Whisper into Real-Time Transcription System"
https://aclanthology.org/2023.ijcnlp-demo.3.pdf
https://github.com/ufal/whisper_streaming

核心思想：
- 维护一个不断累积的音频缓冲区
- 每次收到新音频块（~1s）就在整个缓冲区上重新跑 Whisper
- 当连续两次推理在前缀上达成一致时，把这个前缀"提交"
- 提交后的音频从缓冲区裁掉，剩余的是"未稳定"部分
- 这样既保住了 Whisper 的完整音频上下文（避免幻觉标点），又把首字延迟从 chunk_size 降到 ~2*chunk_size
"""

import os
import numpy as np
from dataclasses import dataclass, field

_DEBUG = os.environ.get("MIMI_STREAM_DEBUG", "").strip() not in ("", "0", "false", "False")


def _debug(msg: str) -> None:
    if _DEBUG:
        print(f"[stream] {msg}", flush=True)


@dataclass
class StreamResult:
    """每次 feed 后返回的结果。"""
    confirmed_text: str = ""        # 新提交的稳定文本（增量，不重复历史）
    tentative_text: str = ""        # 当前未确认的候选文本（每次都会被替换）
    language: str = "unknown"
    confirmed_words: list = field(default_factory=list)  # [{word, start, end}, ...]


class StreamingSTT:
    """每个 speaker 一个实例。

    用法：
        stream = StreamingSTT(stt)
        while audio_chunk := await receive():
            result = stream.feed(audio_chunk)
            if result.confirmed_text:
                # 提交稳定文本（不会再变）
                ...
            # tentative_text 每次都会变，用于显示"正在识别"
            ...
        final = stream.flush()  # 会话结束时强制提交剩余
    """

    MAX_BUFFER_SECONDS = 25.0  # 缓冲区超过这个长度强制提交，避免无限增长
    MIN_BUFFER_SECONDS = 0.5   # 缓冲区不到这个长度就跳过推理
    SILENCE_THRESHOLD = 0.01   # RMS 低于此值认为是静音（float32 [-1,1]，约 -40dB）
    # Voice Processing (AEC+NS) 在前端已过滤回声和噪音，这里只拦截纯数字静音
    SILENCE_FLUSH_SECONDS = 3.0  # 连续静音超过此时长自动 flush buffer

    def __init__(self, stt, sample_rate: int = 16000):
        """
        Args:
            stt: SpeechToText 实例（需要 transcribe_audio 返回包含 segments[].words 的结果）
            sample_rate: 音频采样率
        """
        self.stt = stt
        self.sample_rate = sample_rate
        self.buffer = np.array([], dtype=np.float32)
        # 上次推理的 word 列表 [{word, start, end}, ...]，用于 LocalAgreement-2 比较
        self.last_words: list[dict] = []
        # buffer 起点对应的全局时间偏移（每次提交后增长）
        self.buffer_offset: float = 0.0
        self.last_language: str = "unknown"
        self.silence_duration: float = 0.0  # 连续静音累计时长
        # debug only
        self._real_time: float = 0.0  # 累计喂入音频的真实时长（含跳过的静音）
        self._vad_skip_count: int = 0
        self._vad_skip_secs: float = 0.0
        self._force_commit_count: int = 0

    def feed(self, audio_chunk: np.ndarray) -> StreamResult:
        """喂入新音频块，返回 (新稳定文本, 当前候选文本)。"""
        if audio_chunk.dtype != np.float32:
            audio_chunk = audio_chunk.astype(np.float32)
        if len(audio_chunk.shape) > 1:
            audio_chunk = audio_chunk.mean(axis=1)

        chunk_duration = len(audio_chunk) / self.sample_rate
        self._real_time += chunk_duration

        # === 静音检测（VAD）— 防止 Whisper 对静音幻觉出 "you" / "." ===
        rms = float(np.sqrt(np.mean(audio_chunk ** 2)))
        if rms < self.SILENCE_THRESHOLD:
            self.silence_duration += chunk_duration
            self._vad_skip_count += 1
            self._vad_skip_secs += chunk_duration
            buf_dur = len(self.buffer) / self.sample_rate
            _debug(f"t={self._real_time:6.2f}s rms={rms:.4f} SKIP (silent) "
                   f"buf_dur={buf_dur:.2f}s silence_run={self.silence_duration:.2f}s "
                   f"total_skipped={self._vad_skip_secs:.1f}s")
            # 连续静音超过阈值 → flush buffer 中残留的有声内容
            if self.silence_duration >= self.SILENCE_FLUSH_SECONDS and len(self.buffer) > 0:
                _debug(f"t={self._real_time:6.2f}s SILENCE_FLUSH (silence_run >= {self.SILENCE_FLUSH_SECONDS}s)")
                result = self.flush()
                return result
            return StreamResult(language=self.last_language)

        if self.silence_duration > 0:
            _debug(f"t={self._real_time:6.2f}s VAD_BRIDGE end-of-silence={self.silence_duration:.2f}s "
                   f"(buffer now splices across this gap)")
        self.silence_duration = 0.0

        self.buffer = np.concatenate([self.buffer, audio_chunk])

        # 太短就不跑（首次启动时第 1 个 0.5s 块）
        if len(self.buffer) < self.sample_rate * self.MIN_BUFFER_SECONDS:
            return StreamResult(language=self.last_language)

        # 在整个 buffer 上跑 Whisper
        result = self.stt.transcribe_audio(self.buffer)
        self.last_language = result.get("language", self.last_language)
        words = self._flatten_words(result["segments"])
        words = self._filter_repetitions(words)  # 砍掉 "woo woo woo" 类幻觉

        if not words:
            # buffer 全是静音 — 不动 last_words，也不发任何东西
            return StreamResult(language=self.last_language)

        # === LocalAgreement-2 ===
        # 找当前 hypothesis 和上次 hypothesis 的最长公共前缀（按 word 比较）
        committed_count = self._longest_common_prefix(words, self.last_words)

        # 安全阀：buffer 太长，强制全部提交（防止内存无限增长）
        buffer_duration = len(self.buffer) / self.sample_rate
        if buffer_duration > self.MAX_BUFFER_SECONDS:
            self._force_commit_count += 1
            last_end = float(words[-1]["end"]) if words else 0.0
            _debug(f"t={self._real_time:6.2f}s FORCE_COMMIT #{self._force_commit_count} "
                   f"buf_dur={buffer_duration:.2f}s last_word_end={last_end:.2f}s "
                   f"→ will cut {last_end:.2f}s, leave {buffer_duration - last_end:.2f}s  "
                   f"words_n={len(words)}  "
                   f"sample: {' '.join(w['word'] for w in words[-6:])!r}")
            committed_count = len(words)

        # 提交稳定前缀
        confirmed_text = ""
        confirmed_words: list = []
        if committed_count > 0:
            confirmed_words = words[:committed_count]
            confirmed_text = self._words_to_text(confirmed_words)

            # ⚠️ 关键：必须先用相对 buffer 的时间算 cut，再把时间戳改成全局时间
            # 否则下面 for 循环里 mutate 后，cut_time 会变成全局时间导致截多了
            cut_time_relative = float(confirmed_words[-1]["end"])
            cut_samples = int(cut_time_relative * self.sample_rate)
            cut_samples = min(cut_samples, len(self.buffer))

            # 把时间戳转成全局时间（写到 confirmed_words 里方便外部用）
            for w in confirmed_words:
                w["start"] = float(w["start"]) + self.buffer_offset
                w["end"] = float(w["end"]) + self.buffer_offset

            # tentative 部分文本（在裁剪前先算，因为下面要清空 last_words）
            tentative_words = words[committed_count:]
            tentative_text = self._words_to_text(tentative_words)

            # 截掉已提交的音频
            self.buffer = self.buffer[cut_samples:]
            self.buffer_offset += cut_time_relative

            # last_words 清空：剩余 buffer 下次重新跑会产出新的 hypothesis
            self.last_words = []
            buf_after = len(self.buffer) / self.sample_rate
            _debug(f"t={self._real_time:6.2f}s COMMIT {committed_count}w "
                   f"cut={cut_time_relative:.2f}s buf_after={buf_after:.2f}s "
                   f"text={confirmed_text[:60]!r}")
        else:
            # 没东西提交，记下当前 hypothesis 等下次比对
            self.last_words = words
            tentative_text = self._words_to_text(words)
            buf_dur_now = len(self.buffer) / self.sample_rate
            _debug(f"t={self._real_time:6.2f}s NO_COMMIT buf_dur={buf_dur_now:.2f}s "
                   f"hypothesis_n={len(words)} "
                   f"tentative={tentative_text[:60]!r}")

        return StreamResult(
            confirmed_text=confirmed_text,
            tentative_text=tentative_text,
            language=self.last_language,
            confirmed_words=confirmed_words,
        )

    def debug_stats(self) -> dict:
        """返回本次 session 的累计统计（诊断用）。"""
        return {
            "real_time_s": self._real_time,
            "vad_skip_count": self._vad_skip_count,
            "vad_skip_secs": self._vad_skip_secs,
            "force_commit_count": self._force_commit_count,
        }

    def flush(self) -> StreamResult:
        """强制提交剩余 buffer。会话结束 / speaker 切换时调用。"""
        if len(self.buffer) < self.sample_rate * 0.3:
            self._reset_state()
            return StreamResult(language=self.last_language)

        result = self.stt.transcribe_audio(self.buffer)
        self.last_language = result.get("language", self.last_language)
        words = self._flatten_words(result["segments"])
        words = self._filter_repetitions(words)

        text = ""
        confirmed_words: list = []
        if words:
            confirmed_words = words
            text = self._words_to_text(words)
            for w in confirmed_words:
                w["start"] = float(w["start"]) + self.buffer_offset
                w["end"] = float(w["end"]) + self.buffer_offset

        self._reset_state()
        return StreamResult(
            confirmed_text=text,
            tentative_text="",
            language=self.last_language,
            confirmed_words=confirmed_words,
        )

    def reset(self):
        """完全重置状态（speaker 切换时用）。"""
        self._reset_state()
        self.buffer_offset = 0.0
        self.last_language = "unknown"

    # === Internal helpers ===

    def _reset_state(self):
        self.buffer = np.array([], dtype=np.float32)
        self.last_words = []
        self.silence_duration = 0.0

    @staticmethod
    def _flatten_words(segments: list) -> list:
        """从 segments 列表里把所有 words 拉平成一个列表。"""
        words = []
        for seg in segments:
            for w in seg.get("words", []):
                # 复制成 dict，避免 mutate Whisper 返回的对象
                words.append({
                    "word": w["word"],
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                })
        return words

    @staticmethod
    def _normalize(word: str) -> str:
        """规范化 word 字符串用于比较：去前后空格、转小写、去末尾标点。

        Whisper 偶尔会在末尾加/不加标点，导致同一个词被认为不同。
        """
        return word.strip().rstrip(".,!?;:。，！？；：").lower()

    @classmethod
    def _longest_common_prefix(cls, words_now: list, words_prev: list) -> int:
        """LocalAgreement-2 的核心：求两次 hypothesis 的最长公共前缀长度。"""
        n = 0
        for a, b in zip(words_now, words_prev):
            if cls._normalize(a["word"]) == cls._normalize(b["word"]):
                n += 1
            else:
                break
        return n

    @staticmethod
    def _words_to_text(words: list) -> str:
        """把 word 列表拼成自然文本。Whisper 的 word 通常自带前导空格。"""
        return "".join(w["word"] for w in words).strip()

    @classmethod
    def _filter_repetitions(cls, words: list, max_repeat: int = 4) -> list:
        """检测并截断重复幻觉。

        Whisper 在含糊/短/静音音频上偶尔会输出 100+ 次同一个词
        （比如 "the the the..." 或 "woo woo woo..."）。
        真实人话很少同一个词连续 >4 次。一旦发现，截断到第一次出现处。
        """
        if not words:
            return words
        out: list = []
        last_norm = None
        run = 0
        for w in words:
            norm = cls._normalize(w["word"])
            if norm and norm == last_norm:
                run += 1
                if run > max_repeat:
                    # 发现幻觉 — 截掉这个词以及之后所有内容
                    # 已经加进 out 的最近 max_repeat 次重复也回退一个，避免末尾留垃圾
                    out = out[:-max_repeat + 1] if max_repeat > 1 else out
                    break
                out.append(w)
            else:
                last_norm = norm
                run = 1
                out.append(w)
        return out
