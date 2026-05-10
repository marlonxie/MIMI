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

# 已知 Whisper YouTube 训练数据残留的低能量幻觉短语
# 来源：OpenAI/whisper#928 等社区 issue
_HALLUCINATION_PHRASES = {
    "thank you.", "thank you", "thanks for watching.", "thanks for watching",
    "thanks.", "thanks", "bye.", "bye", "bye-bye.", "bye-bye",
    "you.", "you", "okay.", "okay",
    "danke.", "danke", "tschüss.", "tschüss",
    ".", "。",
}
# 真实 "Thank you." 时长约 0.45-0.8s；< 0.6s 又匹配黑名单 = 几乎可确认幻觉
_PHRASE_DURATION_MAX = 0.6

# Char-level repetition: 单 segment 内 1-4 字符 N-gram 连续重复 ≥ 8 次 = 幻觉
# 例: "ALALALALALALALALAL..." 或 "aaaaaaaa..."。L3 词级 filter 看不到这种内部重复
_CHAR_REPEAT_MIN_RUN = 8


def _is_char_repetition(text: str, min_run: int = _CHAR_REPEAT_MIN_RUN) -> bool:
    """检测 'ALALALAL...' / 'aaaaaaaa...' / 'haha haha ...' 类字符级 N-gram 重复。

    去空格后，对每个 size in (1, 2, 3, 4) 跑滑窗：找连续重复 ≥ min_run 次的 N-gram。
    """
    s = text.replace(" ", "").lower()
    if len(s) < min_run * 2:
        return False
    for size in (1, 2, 3, 4):
        for i in range(len(s) - size * min_run + 1):
            chunk = s[i:i + size]
            if not chunk:
                continue
            run = 1
            j = i + size
            while j + size <= len(s) and s[j:j + size] == chunk:
                run += 1
                j += size
            if run >= min_run:
                return True
    return False


def _debug(msg: str) -> None:
    if _DEBUG:
        print(f"[stream] {msg}", flush=True)


def words_to_text(words: list) -> str:
    """把 word 列表拼成自然文本。Whisper 的 word 通常自带前导空格。"""
    return "".join(w["word"] for w in words).strip()


@dataclass
class StreamResult:
    """每次 feed 后返回的结果。

    confirmed_words 是 canonical：要文本时用 words_to_text(confirmed_words) 派生。
    """
    tentative_text: str = ""        # 当前未确认的候选文本（每次都会被替换）
    language: str = "unknown"
    confirmed_words: list = field(default_factory=list)  # [{word, start, end}, ...]


class StreamingSTT:
    """每个 speaker 一个实例。

    用法：
        stream = StreamingSTT(stt)
        while audio_chunk := await receive():
            result = stream.feed(audio_chunk)
            if result.confirmed_words:
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
    # 幻觉污染保护（filter 全砍后清理 buffer，避免污染后续真实语音）
    NO_SPEECH_PROB_CUT = 0.6      # Whisper 自标 no_speech_prob > 此值 → 精确切到段尾
    EMPTY_FILTER_STREAK_LIMIT = 3  # 连续 N 轮 filter 全砍 → 兜底强 reset
    POLLUTION_RETAIN_SEC = 1.5    # 强 reset 时尾部保留秒数（防止刚开口的真实语音被误删）

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
        # 连续 filter 全砍计数器：达到 EMPTY_FILTER_STREAK_LIMIT 触发 buffer 强 reset
        self._empty_after_filter_streak: int = 0
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
        raw_segments = result["segments"]  # 用 raw 区分"真静默"vs"被过滤"
        # 后置过滤：L2 paper §4.5 combo gate + L4 短促 blacklist
        result["segments"] = self._drop_hallucinations(raw_segments)
        words = self._flatten_words(result["segments"])
        words = self._filter_repetitions(words)  # 砍掉 "woo woo woo" 类幻觉

        if not words:
            # 区分两种情况：
            # (a) Whisper 完全没产 word（真静默）→ 不动 buffer，留给 silence_flush 路径
            # (b) Whisper 产了但被 _drop_hallucinations / _filter_repetitions 砍光
            #     → 这是污染，必须切 buffer，否则下次真实语音被卡到 25s force_commit
            raw_words_existed = any(seg.get("words") for seg in raw_segments)
            if raw_words_existed:
                self._empty_after_filter_streak += 1

                # 策略 A：Whisper 自己标了高 no_speech_prob 的 segment → 精确切到段尾
                # 这是 Whisper 自己提供的边界，无信息损失
                cut_to = 0.0
                for seg in raw_segments:
                    if seg.get("no_speech_prob", 0.0) > self.NO_SPEECH_PROB_CUT:
                        cut_to = max(cut_to, float(seg["end"]))
                if cut_to > 0:
                    cut_samples = min(int(cut_to * self.sample_rate), len(self.buffer))
                    self.buffer = self.buffer[cut_samples:]
                    self.buffer_offset += cut_to
                    self.last_words = []
                    _debug(f"t={self._real_time:6.2f}s NO_SPEECH_CUT to {cut_to:.2f}s "
                           f"(buf now {len(self.buffer)/self.sample_rate:.2f}s)")

                # 策略 B：连续 N 轮 filter 全砍 → 兜底强 reset（处理"自信幻觉"如 ALALAL...）
                elif self._empty_after_filter_streak >= self.EMPTY_FILTER_STREAK_LIMIT:
                    retain_samples = int(self.POLLUTION_RETAIN_SEC * self.sample_rate)
                    if len(self.buffer) > retain_samples:
                        dropped = (len(self.buffer) - retain_samples) / self.sample_rate
                        self.buffer = self.buffer[-retain_samples:]
                        self.buffer_offset += dropped
                        self.last_words = []
                        _debug(f"t={self._real_time:6.2f}s POLLUTION_RESET "
                               f"dropped={dropped:.2f}s kept={self.POLLUTION_RETAIN_SEC}s")
                    self._empty_after_filter_streak = 0
            else:
                # 真静默（Whisper 完全没产 segment.words）→ 重置 streak，让 silence_flush 接管
                self._empty_after_filter_streak = 0
            return StreamResult(language=self.last_language)
        else:
            # 任何成功一帧都重置 streak
            self._empty_after_filter_streak = 0

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
        confirmed_words: list = []
        if committed_count > 0:
            confirmed_words = words[:committed_count]

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
            tentative_text = words_to_text(tentative_words)

            # 截掉已提交的音频
            self.buffer = self.buffer[cut_samples:]
            self.buffer_offset += cut_time_relative

            # last_words 清空：剩余 buffer 下次重新跑会产出新的 hypothesis
            self.last_words = []
            buf_after = len(self.buffer) / self.sample_rate
            if _DEBUG:
                _debug(f"t={self._real_time:6.2f}s COMMIT {committed_count}w "
                       f"cut={cut_time_relative:.2f}s buf_after={buf_after:.2f}s "
                       f"text={words_to_text(confirmed_words)[:60]!r}")
        else:
            # 没东西提交，记下当前 hypothesis 等下次比对
            self.last_words = words
            tentative_text = words_to_text(words)
            buf_dur_now = len(self.buffer) / self.sample_rate
            _debug(f"t={self._real_time:6.2f}s NO_COMMIT buf_dur={buf_dur_now:.2f}s "
                   f"hypothesis_n={len(words)} "
                   f"tentative={tentative_text[:60]!r}")

        return StreamResult(
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
        # 跟 feed() 对称：flush 路径也走幻觉过滤
        result["segments"] = self._drop_hallucinations(result["segments"])
        words = self._flatten_words(result["segments"])
        words = self._filter_repetitions(words)

        confirmed_words: list = []
        if words:
            confirmed_words = words
            for w in confirmed_words:
                w["start"] = float(w["start"]) + self.buffer_offset
                w["end"] = float(w["end"]) + self.buffer_offset

        self._reset_state()
        return StreamResult(
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
    def _drop_hallucinations(segments: list) -> list:
        """三层后置过滤：
        - L2: combo gate (Whisper paper §4.5 needs_fallback)。avg_logprob < -1.0
              OR compression_ratio > 2.4 → drop。OR 比 AND 更激进，能拦住
              "Whisper 高自信吐垃圾"（高 cr，中等 alp）的语言错位 case。阈值
              取 paper 默认 -1.0 / 2.4。正常英语 cr 约 1.4-1.8，不会误杀。
        - L5: char-level repetition (新加)。L3 是词级，看不到单 word 内部
              "ALALALAL..." 这种字符 N-gram 重复。这里整段 segment 直接砍掉。
        - L4: phrase blacklist + duration heuristic。命中已知 YouTube 训练
              数据残留短语且 segment 时长 < 0.6s（真实 "Thank you." 约
              0.45-0.8s）→ 视作咳嗽 / 静默 + Whisper 自动补 "Thank you" 幻觉。
        """
        out = []
        for seg in segments:
            alp = seg.get("avg_logprob", 0.0)
            cr = seg.get("compression_ratio", 1.0)
            if alp < -1.0 or cr > 2.4:
                _debug(f"[hallu-L2] drop alp={alp:.2f} cr={cr:.2f} "
                       f"text={seg['text'][:60]!r}")
                continue

            if _is_char_repetition(seg["text"]):
                _debug(f"[hallu-L5] drop char-repeat text={seg['text'][:60]!r}")
                continue

            text_norm = seg["text"].strip().lower()
            if text_norm in _HALLUCINATION_PHRASES:
                duration = float(seg["end"]) - float(seg["start"])
                if duration < _PHRASE_DURATION_MAX:
                    _debug(f"[hallu-L4] drop dur={duration:.2f}s "
                           f"text={text_norm!r}")
                    continue
            out.append(seg)
        return out

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
