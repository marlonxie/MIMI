"""AudioSource — 每个音频源（系统音频 / 麦克风）的独立处理管道。

两路音频各自一个实例，状态完全独立：
- self.stream: StreamingSTT（独立 buffer / LocalAgreement-2）
- self.segmenter: SentenceSegmenter（独立 pending 缓冲）
- self.partial_id: 当前灰色行的 UUID

speaker 字段是简化的说话人识别（系统音频→interviewer，麦克风→me），
真正的 diarization 作为独立模块叠加（见 audio/speaker_id.py）。
"""

import asyncio
import uuid
import numpy as np
from fastapi import WebSocket

from audio.streaming import StreamingSTT
from conversation.history import SharedHistory
from conversation.segmenter import SentenceSegmenter


class AudioSource:
    """每个音频源的完整处理管道：STT → 分句 → 推送。"""

    def __init__(
        self,
        speaker: str,
        websocket: WebSocket,
        stt_engine,  # 符合 STT 接口：load_model() + transcribe_audio(audio) -> dict
        shared_history: SharedHistory,
        sample_rate: int,
        whisper_lock: asyncio.Lock,
        translator,  # 符合 Translator 接口：translate_stream(text, lang, context)
    ):
        self.speaker = speaker
        self.websocket = websocket
        self.shared_history = shared_history
        self.stream = StreamingSTT(stt_engine, sample_rate=sample_rate)
        self.segmenter = SentenceSegmenter(speaker, shared_history)
        self.partial_id: str | None = None
        self.last_triggered_sentences: list[dict] = []
        self._whisper_lock = whisper_lock
        self._translator = translator

    def pop_partial_id(self) -> str | None:
        pid = self.partial_id
        self.partial_id = None
        return pid

    async def handle_chunk(self, audio_data: np.ndarray):
        """处理一个音频 chunk：Whisper 推理 → 分句 → final 推送 → partial 推送。

        在独立协程里跑（create_task），self.speaker 不会被其他路覆盖。
        """
        # Whisper 推理（GPU 锁保证不和另一路同时跑）
        async with self._whisper_lock:
            result = await asyncio.to_thread(self.stream.feed, audio_data)

        # === confirmed words → 分句 → final 推送 ===
        if result.confirmed_words:
            # 利用词间停顿做自然分句（而非只看 .?!）
            completed = self.segmenter.add_words(result.confirmed_words, result.language)
            if completed:
                prev_id = self.pop_partial_id() or str(uuid.uuid4())
                for i, sentence in enumerate(completed):
                    sentence_id = prev_id if i == 0 else str(uuid.uuid4())
                    insert_after = prev_id if i > 0 else None

                    # sentence 是 shared_history 里同一个 dict 的引用，
                    # 写 id 等于同时写入 history（供 manual_suggest 按 ID 反查）
                    sentence["id"] = sentence_id

                    msg = {
                        "type": "transcript",
                        "sentence_id": sentence_id,
                        "speaker": sentence["speaker"],
                        "language": sentence["language"],
                        "text": sentence["text"],
                        "is_final": True,
                        "timestamp": sentence["timestamp"],
                    }
                    if insert_after is not None:
                        msg["insert_after"] = insert_after
                    await self.websocket.send_json(msg)

                    asyncio.create_task(
                        stream_translation(
                            self.websocket, sentence, self.shared_history,
                            sentence_id, self._translator,
                        )
                    )
                    prev_id = sentence_id
                self.last_triggered_sentences = completed

        # === partial 推送（灰色行） ===
        # 协议拆双段：stable_text 来自 segmenter pending（已 commit，永不变），
        # tentative_text 来自 stream hypothesis 未 commit 部分（可能漂移）。
        # 前端按两段不同稳定性分别渲染，避免"灰色字消失再出现"现象。
        stable_text = self.segmenter.pending_text or ""
        tentative_text = result.tentative_text or ""

        if stable_text or tentative_text:
            if self.partial_id is None:
                self.partial_id = str(uuid.uuid4())
            # text 保留为兼容字段（旧客户端走这条路径）
            if stable_text and tentative_text:
                text = (stable_text + " " + tentative_text).strip()
            else:
                text = stable_text or tentative_text
            await self.websocket.send_json({
                "type": "transcript",
                "sentence_id": self.partial_id,
                "speaker": self.speaker,
                "language": result.language,
                "text": text,
                "stable_text": stable_text,
                "tentative_text": tentative_text,
                "is_final": False,
                "timestamp": self.shared_history.current_timestamp(),
            })

    async def flush(self):
        """强制提交 StreamingSTT 剩余 buffer + SentenceSegmenter pending。"""
        # StreamingSTT flush
        final = self.stream.flush()
        if final.confirmed_words:
            completed = self.segmenter.add_words(final.confirmed_words, final.language)
            if completed:
                prev_id = self.pop_partial_id() or str(uuid.uuid4())
                for i, sentence in enumerate(completed):
                    sentence_id = prev_id if i == 0 else str(uuid.uuid4())
                    sentence["id"] = sentence_id  # 写回 history entry
                    await self.websocket.send_json({
                        "type": "transcript",
                        "sentence_id": sentence_id,
                        "speaker": sentence["speaker"],
                        "language": sentence["language"],
                        "text": sentence["text"],
                        "is_final": True,
                        "timestamp": sentence["timestamp"],
                    })
                    asyncio.create_task(
                        stream_translation(
                            self.websocket, sentence, self.shared_history,
                            sentence_id, self._translator,
                        )
                    )
                    prev_id = sentence_id

        # SentenceSegmenter flush（pending 里可能还有没句末标点的文本）
        flushed = self.segmenter.flush()
        for sentence in flushed:
            sid = self.pop_partial_id() or str(uuid.uuid4())
            sentence["id"] = sid  # 写回 history entry
            await self.websocket.send_json({
                "type": "transcript",
                "sentence_id": sid,
                "speaker": sentence["speaker"],
                "language": sentence["language"],
                "text": sentence["text"],
                "is_final": True,
                "timestamp": sentence["timestamp"],
            })
            asyncio.create_task(
                stream_translation(
                    self.websocket, sentence, self.shared_history,
                    sid, self._translator,
                )
            )


async def stream_translation(
    websocket: WebSocket,
    sentence: dict,
    shared_history: SharedHistory,
    sentence_id: str,
    translator,
):
    """后台协程：流式推翻译 delta + final。

    translator 未就绪（缺 api key）时直接早返回，前端字幕翻译列保持空。
    """
    if not translator.is_ready:
        return
    try:
        context = shared_history.get_context_window()
        full_translation = ""
        async for delta in translator.translate_stream(
            sentence["text"], sentence["language"], context=context
        ):
            full_translation += delta
            await websocket.send_json({
                "type": "translation_delta",
                "sentence_id": sentence_id,
                "delta": delta,
            })

        await websocket.send_json({
            "type": "translation_final",
            "sentence_id": sentence_id,
            "text": full_translation.strip(),
        })
    except Exception as e:
        print(f"翻译推送中止: {type(e).__name__}")
