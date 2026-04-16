"""Whisper 能力测试 — 对比离线 vs 流式（LocalAgreement-2）的分句和标点表现。

目的：
1. 测试 Whisper 离线 segment 边界和词间停顿的关系
2. 对比流式框架下的标点保留率和分句质量
3. 为分句优化提供数据依据

跑法：
    cd mimi-backend
    /Users/marlon/anaconda3/envs/mimi/bin/python tests/test_whisper_capability.py
    # 可选参数：指定音频文件
    /Users/marlon/anaconda3/envs/mimi/bin/python tests/test_whisper_capability.py tests/test_audio_full.wav
"""

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.stt import SpeechToText
from core.stt_stream import StreamingSTT
from core.conversation import SharedHistory, SentenceSegmenter

AUDIO_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "test_audio_full.wav"
CHUNK_SECONDS = 1.0
SENTENCE_ENDINGS = set(".?!")


def load_audio(path):
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0, sr


def split_sentences(text):
    sentences, current = [], ""
    for ch in text:
        current += ch
        if ch in SENTENCE_ENDINGS:
            if current.strip():
                sentences.append(current.strip())
            current = ""
    if current.strip():
        sentences.append(current.strip())
    return sentences


def find_word_pauses(words, min_gap=0.3):
    """找词间停顿 > min_gap 秒的位置"""
    pauses = []
    for i in range(len(words) - 1):
        gap = words[i + 1]["start"] - words[i]["end"]
        if gap > min_gap:
            w = words[i]["word"].strip()
            has_punct = bool(w) and w[-1] in ".,!?;:"
            pauses.append({
                "gap": gap,
                "time": words[i]["end"],
                "word": w,
                "next_word": words[i + 1]["word"].strip(),
                "has_punct": has_punct,
            })
    return pauses


def run_offline(stt, audio_chunk):
    """离线转写：一次性给 Whisper"""
    result = stt.transcribe_audio(audio_chunk)
    segments = result["segments"]
    sentences = split_sentences(result["text"])

    all_words = []
    for s in segments:
        all_words.extend(s.get("words", []))

    pauses = find_word_pauses(all_words)
    punct_count = sum(1 for c in result["text"] if c in SENTENCE_ENDINGS)
    seg_boundaries = [s["end"] for s in segments[:-1]]

    return {
        "text": result["text"],
        "segments": segments,
        "sentences": sentences,
        "words": all_words,
        "pauses": pauses,
        "punct_count": punct_count,
        "seg_boundaries": seg_boundaries,
    }


def run_streaming(stt, audio_chunk, sr):
    """流式转写：1s 切块 + LocalAgreement-2 + SentenceSegmenter"""
    stream = StreamingSTT(stt, sample_rate=sr)
    history = SharedHistory()
    segmenter = SentenceSegmenter("interviewer", history)

    all_confirmed = []
    all_confirmed_words = []
    chunk_size = int(sr * CHUNK_SECONDS)

    for i in range(0, len(audio_chunk), chunk_size):
        c = audio_chunk[i:i + chunk_size]
        r = stream.feed(c)
        if r.confirmed_text:
            all_confirmed.append(r.confirmed_text)
            all_confirmed_words.extend(r.confirmed_words)
            segmenter.add_words(r.confirmed_words, r.language)

    final = stream.flush()
    if final.confirmed_text:
        all_confirmed.append(final.confirmed_text)
        all_confirmed_words.extend(final.confirmed_words)
        segmenter.add_words(final.confirmed_words, final.language)

    flushed = segmenter.flush()

    streaming_text = " ".join(all_confirmed)
    streaming_sentences = [e["text"] for e in history.history]
    streaming_sentences.extend([e["text"] for e in flushed])

    pauses = find_word_pauses(all_confirmed_words)
    punct_count = sum(1 for c in streaming_text if c in SENTENCE_ENDINGS)

    return {
        "text": streaming_text,
        "confirmed_count": len(all_confirmed),
        "sentences": streaming_sentences,
        "words": all_confirmed_words,
        "pauses": pauses,
        "punct_count": punct_count,
    }


def analyze_segment(stt, audio, sr, start_s, end_s):
    """分析一段音频的离线 vs 流式表现"""
    chunk = audio[start_s * sr: end_s * sr]

    offline = run_offline(stt, chunk)
    streaming = run_streaming(stt, chunk, sr)

    # 停顿处有标点的比例
    def pause_punct_rate(pauses):
        if not pauses:
            return 0, 0
        with_punct = sum(1 for p in pauses if p["has_punct"])
        return with_punct, len(pauses)

    off_pp, off_total = pause_punct_rate(offline["pauses"])
    str_pp, str_total = pause_punct_rate(streaming["pauses"])

    # 超长句子
    max_sentence_len = max((len(s) for s in streaming["sentences"]), default=0)
    long_sentences = [s for s in streaming["sentences"] if len(s) > 100]

    # segment 边界 vs 大停顿（>0.5s）边界
    seg_bounds = offline["seg_boundaries"]
    pause_bounds = [p["time"] for p in offline["pauses"] if p["gap"] > 0.5]

    return {
        "range": f"{start_s}-{end_s}s",
        "offline_segments": len(offline["segments"]),
        "offline_sentences": len(offline["sentences"]),
        "offline_puncts": offline["punct_count"],
        "offline_pauses": off_total,
        "offline_pauses_with_punct": off_pp,
        "streaming_confirms": streaming["confirmed_count"],
        "streaming_sentences": len(streaming["sentences"]),
        "streaming_puncts": streaming["punct_count"],
        "streaming_pauses": str_total,
        "streaming_pauses_with_punct": str_pp,
        "max_sentence_len": max_sentence_len,
        "long_sentences": len(long_sentences),
        "seg_boundaries": seg_bounds,
        "pause_boundaries_05": pause_bounds,
        # 详情（供详细查看）
        "_offline": offline,
        "_streaming": streaming,
    }


def main():
    print("=" * 80)
    print("Whisper 能力测试：离线 vs 流式 (LocalAgreement-2)")
    print(f"音频: {AUDIO_PATH}")
    print("=" * 80)

    stt = SpeechToText()
    stt.load_model()
    audio, sr = load_audio(AUDIO_PATH)
    total_s = len(audio) / sr
    print(f"音频: {total_s:.1f}s ({total_s/60:.1f}min) @ {sr}Hz\n")

    # 测试多段 30s 片段
    test_ranges = []
    for start in range(0, min(int(total_s) - 30, 1200), 150):
        test_ranges.append((start, start + 30))
    # 确保至少有开头
    if not test_ranges or test_ranges[0][0] != 0:
        test_ranges.insert(0, (0, 30))

    results = []
    for start, end in test_ranges:
        print(f"分析 {start}-{end}s ...")
        r = analyze_segment(stt, audio, sr, start, end)
        results.append(r)

    # === 汇总表 ===
    print("\n" + "=" * 80)
    print("汇总")
    print("=" * 80)

    header = f"{'范围':>10s} | {'离线seg':>5s} {'离线句':>5s} {'离线标点':>6s} | {'流式句':>5s} {'流式标点':>6s} {'标点差':>5s} | {'最长句':>5s} {'超长':>4s} | {'离线停顿':>7s} {'有标点':>5s} | {'流式停顿':>7s} {'有标点':>5s}"
    print(header)
    print("-" * len(header))

    total_offline_pauses = 0
    total_offline_pp = 0
    total_stream_pauses = 0
    total_stream_pp = 0
    total_long = 0

    for r in results:
        punct_diff = r["streaming_puncts"] - r["offline_puncts"]
        off_pp_pct = f"{r['offline_pauses_with_punct']}/{r['offline_pauses']}" if r["offline_pauses"] else "0/0"
        str_pp_pct = f"{r['streaming_pauses_with_punct']}/{r['streaming_pauses']}" if r["streaming_pauses"] else "0/0"

        print(f"{r['range']:>10s} | {r['offline_segments']:>5d} {r['offline_sentences']:>5d} {r['offline_puncts']:>6d} | {r['streaming_sentences']:>5d} {r['streaming_puncts']:>6d} {punct_diff:>+5d} | {r['max_sentence_len']:>5d} {r['long_sentences']:>4d} | {off_pp_pct:>7s} {r['offline_pauses_with_punct']*100//max(r['offline_pauses'],1):>4d}% | {str_pp_pct:>7s} {r['streaming_pauses_with_punct']*100//max(r['streaming_pauses'],1):>4d}%")

        total_offline_pauses += r["offline_pauses"]
        total_offline_pp += r["offline_pauses_with_punct"]
        total_stream_pauses += r["streaming_pauses"]
        total_stream_pp += r["streaming_pauses_with_punct"]
        total_long += r["long_sentences"]

    # === segment 边界 vs 停顿边界 ===
    print(f"\n{'='*80}")
    print("Segment 边界 vs 停顿(>0.5s) 边界对比")
    print("=" * 80)
    for r in results:
        seg_b = [f"{b:.1f}" for b in r["seg_boundaries"]]
        pau_b = [f"{b:.1f}" for b in r["pause_boundaries_05"]]
        print(f"  {r['range']:>10s}  seg边界: [{', '.join(seg_b)}]")
        print(f"  {'':>10s}  停顿边界: [{', '.join(pau_b)}]")

    # === 总结 ===
    print(f"\n{'='*80}")
    print("总结")
    print("=" * 80)
    print(f"  测试片段数: {len(results)}")
    print(f"  离线停顿>0.3s: {total_offline_pauses} 处, 有标点: {total_offline_pp} ({total_offline_pp*100//max(total_offline_pauses,1)}%)")
    print(f"  流式停顿>0.3s: {total_stream_pauses} 处, 有标点: {total_stream_pp} ({total_stream_pp*100//max(total_stream_pauses,1)}%)")
    print(f"  流式超长句(>100字符): {total_long} 个")
    print(f"\n  结论: 停顿>0.3s处{'几乎都' if total_offline_pp*100//max(total_offline_pauses,1) > 90 else '大部分'}有标点 → 可用词间停顿辅助分句")


if __name__ == "__main__":
    main()
