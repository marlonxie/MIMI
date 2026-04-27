"""partial transcript 字段一致性 + 时序诊断 — 仅采集数据，不做重构。

跑一段音频通过完整 AudioSource pipeline（不连真 WebSocket / server），
monkey-patch 拦截 stream.feed() 和 ws.send_json() 抓字段来源 + 后端状态 + wall-clock 时序，
每帧 dump 到 jsonl，最后输出 summary：
- 字段维度：overlap / repeat-word / final-shrink / preview re-compute mismatch
- 时序维度：每条消息 wall-clock；partial id 切换 gap；partial → final → next partial 间隔；
            同 partial_id 跨帧 text drift（前一帧 partial 文本 vs 当前帧）

跑法：
    cd mimi-backend
    /Users/marlon/anaconda3/envs/mimi/bin/python tests/diagnostics/test_partial_field_audit.py
    /Users/marlon/anaconda3/envs/mimi/bin/python tests/diagnostics/test_partial_field_audit.py path/to/audio.wav
"""

import asyncio
import json
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from audio.source import AudioSource
from audio.stt_mlx import SpeechToText
from conversation.history import SharedHistory


CHUNK_SECONDS = 1.0
SPEAKER = "interviewer"

DEFAULT_AUDIO = Path(__file__).parent.parent / "test_audio.wav"
OUTPUT_DIR = Path(__file__).parent / "output"


# 全局时钟原点：audit 启动瞬间，所有 sent_at_ms 相对它
_T0_NS = 0


def _now_ms() -> float:
    return (time.perf_counter_ns() - _T0_NS) / 1e6


# ───────────────────────── audio I/O ─────────────────────────

def load_audio(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0, sr


# ───────────────────────── mocks ─────────────────────────

class MockWebSocket:
    """收集 send_json 调用，不做任何 I/O。"""

    def __init__(self):
        self.messages: list[dict] = []

    async def send_json(self, msg: dict):
        self.messages.append(dict(msg))  # copy


class MockTranslator:
    """空翻译器：translate_stream 返回空 async generator（不走真翻译）。"""

    async def translate_stream(self, *_args, **_kwargs):
        if False:  # pragma: no cover - 让函数变成 async generator 但永不 yield
            yield ""


# ───────────────────────── word-level helpers ─────────────────────────

def _normalize(word: str) -> str:
    return word.strip().rstrip(".,!?;:。，！？；：").lower()


def detect_word_overlap(pending: str, tentative: str) -> list[str]:
    """找 tentative 前缀和 pending 后缀的最大词级重叠。"""
    pw = [_normalize(w) for w in pending.split() if w.strip()]
    tw_raw = [w for w in tentative.split() if w.strip()]
    tw = [_normalize(w) for w in tw_raw]
    if not pw or not tw:
        return []
    max_k = min(len(pw), len(tw))
    for k in range(max_k, 0, -1):
        if pw[-k:] == tw[:k]:
            return tw_raw[:k]
    return []


def detect_repeat_words(text: str) -> list[dict]:
    """连续重复词：normalize 后相同。返回 [{position, a, b}]"""
    words = text.split()
    out = []
    for i in range(len(words) - 1):
        a = _normalize(words[i])
        b = _normalize(words[i + 1])
        if a and a == b:
            out.append({"position": i, "a": words[i], "b": words[i + 1]})
    return out


def words_diff(a_text: str, b_text: str) -> tuple[list[str], list[str]]:
    """返回 (a 有 b 没有, b 有 a 没有) 的词列表（词袋差）。"""
    aw = a_text.split()
    bw = b_text.split()
    aw_norm = [_normalize(w) for w in aw]
    bw_norm = [_normalize(w) for w in bw]
    a_only = [w for w, n in zip(aw, aw_norm) if n and n not in bw_norm]
    b_only = [w for w, n in zip(bw, bw_norm) if n and n not in aw_norm]
    return a_only, b_only


# ───────────────────────── audit instrumentation ─────────────────────────

def setup_audit(source: AudioSource, ws: MockWebSocket) -> dict:
    """monkey-patch stream.feed 和 ws.send_json 抓 audit 字段 + 时序。

    Returns:
        共享 state dict（保留 last_result 引用，给摘要打印用）
    """
    state: dict = {
        "last_result": None,
        "last_committed_count": 0,
        "feed_t_ms": None,        # 最近一次 stream.feed 完成的时间戳
    }

    real_feed = source.stream.feed
    def captured_feed(audio):
        r = real_feed(audio)
        state["last_result"] = r
        state["last_committed_count"] = len(r.confirmed_words)
        state["feed_t_ms"] = _now_ms()
        return r
    source.stream.feed = captured_feed  # type: ignore[assignment]

    real_send = ws.send_json
    async def instrumented_send(msg: dict):
        if msg.get("type") == "transcript":
            sent_at = _now_ms()
            audit: dict = {
                "sent_at_ms": round(sent_at, 2),
                "since_feed_ms": (
                    round(sent_at - state["feed_t_ms"], 2)
                    if state["feed_t_ms"] is not None else None
                ),
                "pending_text_at_send": source.segmenter.pending_text,
                "pending_words_count": len(source.segmenter._pending_words),
                "tentative_text_at_send": (
                    state["last_result"].tentative_text if state["last_result"] else ""
                ),
                "stream_committed_count_this_chunk": state["last_committed_count"],
                "stream_buffer_offset": round(source.stream.buffer_offset, 3),
                "stream_buffer_dur_s": round(
                    len(source.stream.buffer) / source.stream.sample_rate, 3
                ),
                "stream_last_words_count": len(source.stream.last_words),
            }
            if not msg.get("is_final"):
                pending = audit["pending_text_at_send"]
                tentative = audit["tentative_text_at_send"]
                preview_recomputed = pending
                if tentative:
                    preview_recomputed = (
                        (preview_recomputed + " " + tentative).strip()
                        if preview_recomputed else tentative
                    )
                audit["preview_recomputed"] = preview_recomputed
                audit["preview_matches_msg"] = preview_recomputed == msg["text"]
                overlap = detect_word_overlap(pending, tentative)
                audit["overlap_words"] = overlap
                audit["overlap_detected"] = bool(overlap)
                audit["repeat_words"] = detect_repeat_words(msg["text"])
            msg["_audit"] = audit
        await real_send(msg)
    ws.send_json = instrumented_send  # type: ignore[assignment]

    return state


def snapshot(source: AudioSource) -> dict:
    return {
        "partial_id": source.partial_id,
        "stream_buffer_dur_s": round(
            len(source.stream.buffer) / source.stream.sample_rate, 3
        ),
        "stream_buffer_offset": round(source.stream.buffer_offset, 3),
        "stream_last_words": [w["word"] for w in source.stream.last_words],
        "segmenter_pending_words": [w["word"] for w in source.segmenter._pending_words],
        "segmenter_pending_text": source.segmenter.pending_text,
    }


# ───────────────────────── runner ─────────────────────────

async def run_audit(audio_path: Path, output_path: Path) -> dict:
    print(f"加载音频: {audio_path}")
    audio, sr = load_audio(audio_path)
    print(f"  音频: {len(audio)/sr:.1f}s @ {sr}Hz")

    print("加载 STT...")
    stt = SpeechToText()
    stt.load_model()

    history = SharedHistory()
    ws = MockWebSocket()
    lock = asyncio.Lock()
    translator = MockTranslator()

    source = AudioSource(
        speaker=SPEAKER,
        websocket=ws,
        stt_engine=stt,
        shared_history=history,
        sample_rate=sr,
        whisper_lock=lock,
        translator=translator,
    )

    setup_audit(source, ws)

    chunk_samples = int(sr * CHUNK_SECONDS)
    last_msg_count = 0
    frames: list[dict] = []

    # 时钟原点：模型加载完后才开始计时（避免被加载耗时污染）
    global _T0_NS
    _T0_NS = time.perf_counter_ns()

    print(f"\n开始跑（chunk={CHUNK_SECONDS}s）...")
    for i in range(0, len(audio), chunk_samples):
        chunk = audio[i:i + chunk_samples]
        if len(chunk) < chunk_samples * 0.5:
            break  # 跳过末尾不足半个 chunk 的尾巴

        t_in = _now_ms()
        pre = snapshot(source)
        await source.handle_chunk(chunk)
        post = snapshot(source)
        t_out = _now_ms()

        new_msgs = ws.messages[last_msg_count:]
        last_msg_count = len(ws.messages)

        frame = {
            "chunk_index": i // chunk_samples,
            "audio_t_s": round((i + len(chunk)) / sr, 2),
            "wall_t_in_ms": round(t_in, 2),
            "wall_t_out_ms": round(t_out, 2),
            "wall_dur_ms": round(t_out - t_in, 2),
            "pre": pre,
            "post": post,
            "messages": new_msgs,
        }
        frames.append(frame)

    # 让后台 stream_translation 的 create_task 跑完（empty generator 立刻完成）
    await asyncio.sleep(0.05)

    print(f"\n跑完 {len(frames)} 个 chunk，写入 {output_path}")
    with output_path.open("w", encoding="utf-8") as f:
        for fr in frames:
            f.write(json.dumps(fr, ensure_ascii=False) + "\n")

    return {"frames": frames, "all_messages": list(ws.messages)}


# ───────────────────────── summary ─────────────────────────

def _frame_msg_classes(frame: dict) -> tuple[bool, bool]:
    """returns (has_partial, has_final)"""
    has_p = has_f = False
    for m in frame["messages"]:
        if m.get("type") != "transcript":
            continue
        if m.get("is_final"):
            has_f = True
        else:
            has_p = True
    return has_p, has_f


def _analyze_timing(frames: list[dict], transcripts: list[dict]) -> dict:
    """所有时序相关的统计：partial 缺帧、partial-id 切换 gap、partial→final→next partial 间隔、
    同 partial_id 跨帧 text drift。"""

    # === per-chunk 类型分布 ===
    chunk_classes = []  # ('PARTIAL_ONLY' | 'FINAL_ONLY' | 'BOTH' | 'NONE')
    for fr in frames:
        has_p, has_f = _frame_msg_classes(fr)
        if has_p and has_f:
            chunk_classes.append("BOTH")
        elif has_p:
            chunk_classes.append("PARTIAL_ONLY")
        elif has_f:
            chunk_classes.append("FINAL_ONLY")
        else:
            chunk_classes.append("NONE")

    # === partial_id 续传 / 切换序列 ===
    # 同一 partial_id 跨多帧的 text 演变
    drift_by_id: dict[str, list[dict]] = {}
    for fr in frames:
        for m in fr["messages"]:
            if m.get("type") != "transcript" or m.get("is_final"):
                continue
            sid = m["sentence_id"]
            drift_by_id.setdefault(sid, []).append({
                "chunk": fr["chunk_index"],
                "audio_t": fr["audio_t_s"],
                "sent_at_ms": m["_audit"]["sent_at_ms"],
                "text": m["text"],
                "pending": m["_audit"]["pending_text_at_send"],
                "tentative": m["_audit"]["tentative_text_at_send"],
                "committed_this_chunk": m["_audit"]["stream_committed_count_this_chunk"],
            })

    # 同一 id 的 text 差异：找 text 缩短或大改的事件
    drift_events: list[dict] = []
    for sid, history in drift_by_id.items():
        if len(history) < 2:
            continue
        for i in range(1, len(history)):
            a, b = history[i - 1], history[i]
            a_only, b_only = words_diff(a["text"], b["text"])
            if a_only or b_only:
                drift_events.append({
                    "sentence_id": sid,
                    "from_chunk": a["chunk"],
                    "to_chunk": b["chunk"],
                    "from_text": a["text"],
                    "to_text": b["text"],
                    "lost_words": a_only,    # 上一帧有这帧没有
                    "added_words": b_only,   # 这帧新出现的
                    "dt_ms": round(b["sent_at_ms"] - a["sent_at_ms"], 1),
                })

    # === 跨 partial_id 的"消失再出现"gap ===
    # 用户视觉的"灰色行不见了" = 当前 partial 行 ID 还在前端，下一条 partial 是不同 id 时
    # 算从"最后一条 partial(P1)" → "下一条 partial(P2 不同 id)" 的 wall-clock gap
    id_switch_gaps: list[dict] = []
    last_partial_by_chunk: list[dict] = []  # 顺序排
    for fr in frames:
        for m in fr["messages"]:
            if m.get("type") != "transcript" or m.get("is_final"):
                continue
            last_partial_by_chunk.append({"chunk": fr["chunk_index"], "msg": m})
    for i in range(1, len(last_partial_by_chunk)):
        prev = last_partial_by_chunk[i - 1]
        curr = last_partial_by_chunk[i]
        if prev["msg"]["sentence_id"] != curr["msg"]["sentence_id"]:
            id_switch_gaps.append({
                "prev_chunk": prev["chunk"],
                "curr_chunk": curr["chunk"],
                "prev_sid": prev["msg"]["sentence_id"][:8],
                "curr_sid": curr["msg"]["sentence_id"][:8],
                "prev_text": prev["msg"]["text"],
                "curr_text": curr["msg"]["text"],
                "gap_ms": round(
                    curr["msg"]["_audit"]["sent_at_ms"]
                    - prev["msg"]["_audit"]["sent_at_ms"], 1
                ),
            })

    # === partial → final → next partial 三连 ===
    # 对每个 final，找它前面最后一条同 id partial（如有）+ 它后面下一条 partial
    triple_gaps: list[dict] = []
    msg_with_chunk: list[dict] = []
    for fr in frames:
        for m in fr["messages"]:
            if m.get("type") == "transcript":
                msg_with_chunk.append({"chunk": fr["chunk_index"], "msg": m})
    for i, item in enumerate(msg_with_chunk):
        m = item["msg"]
        if not m.get("is_final"):
            continue
        sid = m["sentence_id"]
        # 找前面最后一条同 id partial
        prev_partial = None
        for j in range(i - 1, -1, -1):
            mm = msg_with_chunk[j]["msg"]
            if mm.get("type") != "transcript" or mm.get("is_final"):
                continue
            if mm["sentence_id"] == sid:
                prev_partial = msg_with_chunk[j]
                break
            else:
                break  # id 都换了，没有同 id partial
        # 找后面第一条 partial（任意 id）
        next_partial = None
        for j in range(i + 1, len(msg_with_chunk)):
            mm = msg_with_chunk[j]["msg"]
            if mm.get("type") != "transcript" or mm.get("is_final"):
                continue
            next_partial = msg_with_chunk[j]
            break
        if not prev_partial:
            continue
        ts_prev = prev_partial["msg"]["_audit"]["sent_at_ms"]
        ts_final = m["_audit"]["sent_at_ms"]
        ts_next = (
            next_partial["msg"]["_audit"]["sent_at_ms"] if next_partial else None
        )
        triple_gaps.append({
            "sid_short": sid[:8],
            "prev_partial_chunk": prev_partial["chunk"],
            "final_chunk": item["chunk"],
            "next_partial_chunk": next_partial["chunk"] if next_partial else None,
            "prev_partial_text": prev_partial["msg"]["text"],
            "final_text": m["text"],
            "next_partial_text": next_partial["msg"]["text"] if next_partial else None,
            "prev_to_final_ms": round(ts_final - ts_prev, 1),
            "final_to_next_partial_ms": (
                round(ts_next - ts_final, 1) if ts_next is not None else None
            ),
            "next_partial_sid_same": (
                next_partial["msg"]["sentence_id"] == sid if next_partial else None
            ),
        })

    return {
        "chunk_classes": chunk_classes,
        "drift_events": drift_events,
        "id_switch_gaps": id_switch_gaps,
        "triple_gaps": triple_gaps,
        "drift_by_id": drift_by_id,
    }


def summarize(audit: dict) -> None:
    frames = audit["frames"]
    all_msgs = audit["all_messages"]

    transcripts = [m for m in all_msgs if m.get("type") == "transcript"]
    partials = [m for m in transcripts if not m.get("is_final")]
    finals = [m for m in transcripts if m.get("is_final")]

    no_commit_partials = [
        m for m in partials
        if m.get("_audit", {}).get("stream_committed_count_this_chunk") == 0
    ]
    overlaps = [m for m in partials if m.get("_audit", {}).get("overlap_detected")]
    repeats = [m for m in partials if m.get("_audit", {}).get("repeat_words")]
    preview_mismatch = [
        m for m in partials if m.get("_audit", {}).get("preview_matches_msg") is False
    ]

    # final-shrink: 同 sentence_id 上最近一条 partial → final 比对
    last_partial_by_id: dict[str, dict] = {}
    shrinks: list[dict] = []
    for m in transcripts:
        sid = m["sentence_id"]
        if not m.get("is_final"):
            last_partial_by_id[sid] = m
        else:
            prev = last_partial_by_id.pop(sid, None)
            if prev:
                a_only, _ = words_diff(prev["text"], m["text"])
                if a_only:
                    shrinks.append({
                        "sentence_id": sid,
                        "prev_partial_text": prev["text"],
                        "final_text": m["text"],
                        "vanished_words": a_only,
                        "prev_audit": prev.get("_audit", {}),
                    })

    timing = _analyze_timing(frames, transcripts)
    chunk_classes = timing["chunk_classes"]
    drift_events = timing["drift_events"]
    id_switch_gaps = timing["id_switch_gaps"]
    triple_gaps = timing["triple_gaps"]

    klass_counts = {
        "PARTIAL_ONLY": chunk_classes.count("PARTIAL_ONLY"),
        "FINAL_ONLY": chunk_classes.count("FINAL_ONLY"),
        "BOTH": chunk_classes.count("BOTH"),
        "NONE": chunk_classes.count("NONE"),
    }

    print("\n" + "=" * 70)
    print("=== Partial Field Audit Summary ===")
    print("=" * 70)
    print(f"Total chunks fed:                      {len(frames)}")
    print(f"Transcript messages (partial+final):   {len(transcripts)}")
    print(f"  partial:                             {len(partials)}")
    print(f"  final:                               {len(finals)}")
    print(f"NO_COMMIT partials (committed=0):      {len(no_commit_partials)} / {len(partials)}")
    print(f"Overlap detections:                    {len(overlaps)}")
    print(f"Repeat-word detections in partial:     {len(repeats)}")
    print(f"Preview re-compute mismatch:           {len(preview_mismatch)}")
    print(f"Final-shrink detections:               {len(shrinks)}")

    print("\n--- 时序分布（每 chunk 类型）---")
    print(f"  PARTIAL_ONLY (只发 partial):         {klass_counts['PARTIAL_ONLY']}")
    print(f"  FINAL_ONLY   (只发 final):           {klass_counts['FINAL_ONLY']}")
    print(f"  BOTH         (final + 紧接新 partial):{klass_counts['BOTH']}")
    print(f"  NONE         (本 chunk 没发 transcript):{klass_counts['NONE']}  ⚠️ 用户视觉空窗")

    print(f"\n--- partial_id 切换 (同 id 续传 → 不同 id) 共 {len(id_switch_gaps)} 次 ---")
    for ev in id_switch_gaps[:8]:
        print(f"  chunk {ev['prev_chunk']}→{ev['curr_chunk']}  "
              f"id {ev['prev_sid']}→{ev['curr_sid']}  gap={ev['gap_ms']}ms")
        print(f"    prev: {ev['prev_text']!r}")
        print(f"    curr: {ev['curr_text']!r}")

    print(f"\n--- partial → final → next partial 三连 共 {len(triple_gaps)} 次 ---")
    for ev in triple_gaps[:8]:
        same_id_marker = (
            "(same id)" if ev["next_partial_sid_same"]
            else "(NEW id)" if ev["next_partial_sid_same"] is False
            else ""
        )
        print(f"  sid={ev['sid_short']}  chunks {ev['prev_partial_chunk']}→{ev['final_chunk']}"
              f"→{ev['next_partial_chunk']}")
        print(f"    prev partial → final: {ev['prev_to_final_ms']}ms  "
              f"final → next partial: {ev['final_to_next_partial_ms']}ms {same_id_marker}")
        print(f"    prev partial: {ev['prev_partial_text']!r}")
        print(f"    final       : {ev['final_text']!r}")
        print(f"    next partial: {ev['next_partial_text']!r}")

    print(f"\n--- 同 partial_id 跨帧 drift 事件 共 {len(drift_events)} 次 ---")
    for ev in drift_events[:10]:
        kind = []
        if ev["lost_words"]:
            kind.append(f"LOST {ev['lost_words']}")
        if ev["added_words"]:
            kind.append(f"ADDED {ev['added_words']}")
        print(f"  sid={ev['sentence_id'][:8]}  chunk {ev['from_chunk']}→{ev['to_chunk']}  "
              f"dt={ev['dt_ms']}ms  {' / '.join(kind)}")
        print(f"    {ev['from_text']!r}")
        print(f"    → {ev['to_text']!r}")

    def _print_examples(label: str, items: list, formatter, k: int = 5) -> None:
        if not items:
            return
        print(f"\n--- {label} (showing {min(k, len(items))} / {len(items)}) ---")
        for it in items[:k]:
            formatter(it)

    _print_examples(
        "Overlap", overlaps,
        lambda m: print(
            f"  sid={m['sentence_id'][:8]} text={m['text']!r}\n"
            f"    pending  : {m['_audit']['pending_text_at_send']!r}\n"
            f"    tentative: {m['_audit']['tentative_text_at_send']!r}\n"
            f"    overlap  : {m['_audit']['overlap_words']}"
        ),
    )

    _print_examples(
        "Repeat words in partial", repeats,
        lambda m: print(
            f"  sid={m['sentence_id'][:8]} text={m['text']!r}\n"
            f"    repeats: {m['_audit']['repeat_words']}"
        ),
    )

    _print_examples(
        "Final-shrink", shrinks,
        lambda s: print(
            f"  sid={s['sentence_id'][:8]}\n"
            f"    prev partial: {s['prev_partial_text']!r}\n"
            f"    final       : {s['final_text']!r}\n"
            f"    vanished    : {s['vanished_words']}\n"
            f"    (prev pending={s['prev_audit'].get('pending_text_at_send')!r}, "
            f"tentative={s['prev_audit'].get('tentative_text_at_send')!r})"
        ),
    )

    if preview_mismatch:
        _print_examples(
            "Preview re-compute mismatch (audit ≠ msg.text)", preview_mismatch,
            lambda m: print(
                f"  sid={m['sentence_id'][:8]}\n"
                f"    msg.text         : {m['text']!r}\n"
                f"    preview_recomputed: {m['_audit']['preview_recomputed']!r}"
            ),
        )


# ───────────────────────── entry ─────────────────────────

def main() -> None:
    audio_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_AUDIO
    if not audio_path.exists():
        print(f"音频不存在: {audio_path}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"partial_audit_{ts}.jsonl"

    audit = asyncio.run(run_audit(audio_path, output_path))
    summarize(audit)
    print(f"\n输出: {output_path}")


if __name__ == "__main__":
    main()
