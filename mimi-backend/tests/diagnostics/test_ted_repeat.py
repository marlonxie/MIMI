"""TED 音频字幕 3 次重复测试。

纯离线跑 StreamingSTT + SentenceSegmenter（跳过 WebSocket / 翻译），同一段音频
独立跑 3 次，检测：
- 每次的句数、字数、耗时
- Unigram / Bigram / Trigram 连续重复幻觉
- 3 次之间的结果一致性（字符级 SequenceMatcher.ratio）
- 与参考 transcript 的字符级相似度

跑法：
    cd mimi-backend
    /Users/marlon/anaconda3/envs/mimi/bin/python tests/diagnostics/test_ted_repeat.py

    # 可选：指定其他音频
    /Users/marlon/anaconda3/envs/mimi/bin/python tests/diagnostics/test_ted_repeat.py tests/fixtures/ted_crispin_16k.wav
"""

import sys
import time
import wave
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from audio.stt_mlx import SpeechToText
from audio.streaming import StreamingSTT
from conversation.history import SharedHistory
from conversation.segmenter import SentenceSegmenter

# 对照实验开关：--no-vad-skip 把 SILENCE_THRESHOLD 调到 -1，
# 强制所有 chunk 都进 buffer，不再按 RMS 跳过静音。
NO_VAD_SKIP = "--no-vad-skip" in sys.argv
if NO_VAD_SKIP:
    sys.argv.remove("--no-vad-skip")
    StreamingSTT.SILENCE_THRESHOLD = -1.0
    print("⚠️  VAD skip DISABLED (SILENCE_THRESHOLD = -1)")

FIXTURES = Path(__file__).parent.parent / "fixtures"
AUDIO = Path(sys.argv[1]) if len(sys.argv) > 1 else FIXTURES / "ted_crispin_3min.wav"
# 参考 transcript：文件名基于音频名自动对应
# ted_crispin_3min.wav → ted_crispin_3min_transcript.txt
# ted_crispin_16k.wav  → ted_crispin_transcript.txt (完整版)
_stem = AUDIO.stem.replace("_16k", "")
REF_TRANSCRIPT = FIXTURES / f"{_stem}_transcript.txt"
if not REF_TRANSCRIPT.exists():
    REF_TRANSCRIPT = FIXTURES / "ted_crispin_transcript.txt"  # fallback 完整版
CHUNK_SECONDS = 1.0
NUM_RUNS = 3


def load_audio(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0, sr


def run_once(stt: SpeechToText, audio: np.ndarray, sr: int, run_id: int) -> tuple[list[str], str, float, dict]:
    """一次完整的流式推理，返回 (sentences, full_text, elapsed, stream_stats)。

    每 30s 音频打印一次进度，避免长时间无输出假死。
    """
    stream = StreamingSTT(stt, sample_rate=sr)
    history = SharedHistory()
    seg = SentenceSegmenter("interviewer", history)

    chunk_samples = int(sr * CHUNK_SECONDS)
    total_duration = len(audio) / sr
    progress_every = 30  # 每处理 30s 音频打印一次进度
    next_progress = progress_every

    t0 = time.time()
    for i in range(0, len(audio), chunk_samples):
        r = stream.feed(audio[i:i + chunk_samples])
        if r.confirmed_text:
            seg.add_words(r.confirmed_words, r.language)

        audio_elapsed = (i + chunk_samples) / sr
        if audio_elapsed >= next_progress:
            wall = time.time() - t0
            print(f"    [Run {run_id}] 进度 {audio_elapsed:.0f}/{total_duration:.0f}s"
                  f"  (wall {wall:.0f}s, {len(history.history)} 句)",
                  flush=True)
            next_progress += progress_every

    final = stream.flush()
    if final.confirmed_text:
        seg.add_words(final.confirmed_words, final.language)
    seg.flush()
    elapsed = time.time() - t0

    sentences = [e["text"] for e in history.history]
    full_text = " ".join(sentences)
    stream_stats = stream.debug_stats()
    return sentences, full_text, elapsed, stream_stats


def _normalize_token(w: str) -> str:
    return w.lower().rstrip(".,!?;:")


def detect_ngram_hallucinations(text: str, n: int, max_repeat: int = 4) -> list[tuple[int, tuple, int]]:
    """找连续 >max_repeat 次相同 n-gram 的位置。

    返回 [(start_word_idx, ngram_tuple, count), ...]
    """
    words = text.split()
    hits: list[tuple[int, tuple, int]] = []
    i = 0
    while i + n <= len(words):
        gram = tuple(_normalize_token(w) for w in words[i:i + n])
        # 跳过空 n-gram（纯标点等）
        if any(not g for g in gram):
            i += 1
            continue

        repeats = 1
        j = i + n
        while j + n <= len(words):
            next_gram = tuple(_normalize_token(w) for w in words[j:j + n])
            if next_gram == gram:
                repeats += 1
                j += n
            else:
                break

        if repeats > max_repeat:
            hits.append((i, gram, repeats))
            i = j  # 跳过整个重复段
        else:
            i += 1
    return hits


def main():
    print("=" * 75)
    print("TED 音频字幕 3 次重复测试")
    print(f"音频: {AUDIO}")
    print("=" * 75)

    if not AUDIO.exists():
        print(f"❌ 音频文件不存在: {AUDIO}")
        print("请先下载（见 plan 里的 yt-dlp + ffmpeg 命令）")
        sys.exit(1)

    stt = SpeechToText()
    stt.load_model()
    audio, sr = load_audio(AUDIO)
    duration_s = len(audio) / sr
    print(f"音频长度: {duration_s:.1f}s ({duration_s/60:.1f} 分钟) @ {sr}Hz\n")

    # 输出文件后缀：VAD on / off 各走一套，避免互相覆盖
    suffix = "_novad" if NO_VAD_SKIP else ""

    runs: list[dict] = []
    for run_idx in range(1, NUM_RUNS + 1):
        print(f"--- Run {run_idx}/{NUM_RUNS} 开始 ---")
        sentences, full_text, elapsed, stream_stats = run_once(stt, audio, sr, run_idx)
        uni = detect_ngram_hallucinations(full_text, n=1)
        bi = detect_ngram_hallucinations(full_text, n=2)
        tri = detect_ngram_hallucinations(full_text, n=3)

        runs.append({
            "id": run_idx,
            "sentences": sentences,
            "text": full_text,
            "elapsed": elapsed,
            "unigram": uni,
            "bigram": bi,
            "trigram": tri,
            "stream_stats": stream_stats,
        })

        # 保存每次结果
        out_path = FIXTURES / f"ted_run_{run_idx}{suffix}.txt"
        out_path.write_text("\n".join(sentences), encoding="utf-8")

        print(f"  完成: {len(sentences)} 句, {len(full_text.split())} 词, 耗时 {elapsed:.1f}s")
        print(f"  幻觉: unigram={len(uni)}, bigram={len(bi)}, trigram={len(tri)}")
        print(f"  stream: VAD skip {stream_stats['vad_skip_count']} 次 "
              f"({stream_stats['vad_skip_secs']:.1f}s), "
              f"force_commit {stream_stats['force_commit_count']} 次, "
              f"真实音频 {stream_stats['real_time_s']:.1f}s")
        print(f"  输出: {out_path.relative_to(FIXTURES.parent.parent)}")

    # ============ 汇总报告 ============
    print()
    print("=" * 75)
    print(" 汇总报告")
    print("=" * 75)

    header = f"{'Run':<5}{'Sentences':<12}{'Words':<10}{'Elapsed(s)':<14}{'1-gram':<10}{'2-gram':<10}{'3-gram':<10}"
    print(header)
    print("-" * 75)
    for r in runs:
        words = len(r["text"].split())
        print(f"{r['id']:<5}{len(r['sentences']):<12}{words:<10}"
              f"{r['elapsed']:<14.1f}{len(r['unigram']):<10}{len(r['bigram']):<10}"
              f"{len(r['trigram']):<10}")

    # 幻觉详情
    any_hallu = any(r["bigram"] or r["trigram"] for r in runs)
    if any_hallu:
        print()
        print("-" * 75)
        print(" 幻觉详情（bigram/trigram >4 次连续重复）")
        print("-" * 75)
        for r in runs:
            if r["bigram"] or r["trigram"]:
                print(f"\n  Run {r['id']}:")
                for idx, gram, count in r["bigram"]:
                    print(f"    [bigram x{count}] @word:{idx}  ({gram[0]} {gram[1]})")
                for idx, gram, count in r["trigram"]:
                    print(f"    [trigram x{count}] @word:{idx}  ({' '.join(gram)})")
    else:
        print("\n✓ 没有检测到 bigram / trigram 级幻觉")

    # 跨 run 一致性
    if len(runs) >= 2:
        print()
        print("-" * 75)
        print(" 跨 run 字符级一致性")
        print("-" * 75)
        pairs = [(0, 1), (1, 2), (0, 2)]
        for a, b in pairs:
            ratio = SequenceMatcher(None, runs[a]["text"], runs[b]["text"]).ratio()
            print(f"  Run {runs[a]['id']} vs Run {runs[b]['id']}: {ratio:.1%}")

    # 与参考 transcript 对比
    if REF_TRANSCRIPT.exists():
        ref = REF_TRANSCRIPT.read_text(encoding="utf-8").strip()
        ref_len = len(ref)
        ref_words = len(ref.split())
        print()
        print("-" * 75)
        print(f" 与参考 transcript 对比 ({ref_len} 字符, {ref_words} 词)")
        print("-" * 75)
        for r in runs:
            ratio = SequenceMatcher(None, r["text"], ref).ratio()
            r_len = len(r["text"])
            diff_pct = (r_len - ref_len) / ref_len * 100
            print(f"  Run {r['id']}: similarity={ratio:.1%}, "
                  f"长度 {r_len} ({diff_pct:+.0f}% vs 参考)")
    else:
        print(f"\n⚠️  参考 transcript 不存在: {REF_TRANSCRIPT}")


if __name__ == "__main__":
    main()
