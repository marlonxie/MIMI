"""Whisper 后端性能对比脚本。

比较 openai/whisper (CPU) vs mlx-whisper (GPU+ANE) vs faster-whisper (CPU int8)。
关键指标：推理速度、word_timestamps 完整性、转写一致性。

跑法：
    cd mimi-backend
    python scripts/bench_whisper.py
"""

import time
from pathlib import Path

AUDIO_PATH = str(Path(__file__).parent.parent / "tests" / "test_audio.wav")
MODEL_SIZE = "small"


def bench_openai_whisper():
    print("\n[1] openai/whisper (CPU baseline)")
    import whisper
    t0 = time.time()
    model = whisper.load_model(MODEL_SIZE)
    print(f"  load: {time.time() - t0:.2f}s")

    t0 = time.time()
    result = model.transcribe(AUDIO_PATH, word_timestamps=True)
    elapsed = time.time() - t0
    print(f"  transcribe: {elapsed:.2f}s")
    print(f"  language: {result.get('language')}")
    print(f"  text[:100]: {result['text'][:100]}")

    # 检查 word_timestamps
    segs = result.get("segments", [])
    has_words = bool(segs) and bool(segs[0].get("words"))
    print(f"  has word_timestamps: {has_words}")
    if has_words:
        first_words = segs[0]["words"][:3]
        print(f"  first 3 words: {first_words}")
    return elapsed, result["text"], has_words


def bench_mlx_whisper():
    print("\n[2] mlx-whisper (Metal GPU + ANE)")
    import mlx_whisper
    repo = f"mlx-community/whisper-{MODEL_SIZE}-mlx-q4"

    # 第一次跑：包含模型下载和加载
    print(f"  warming up (model: {repo})...")
    t0 = time.time()
    _ = mlx_whisper.transcribe(AUDIO_PATH, path_or_hf_repo=repo, word_timestamps=False)
    print(f"  warmup (incl. download/load): {time.time() - t0:.2f}s")

    # 第二次跑：实际计时
    t0 = time.time()
    result = mlx_whisper.transcribe(
        AUDIO_PATH,
        path_or_hf_repo=repo,
        word_timestamps=True,
    )
    elapsed = time.time() - t0
    print(f"  transcribe: {elapsed:.2f}s")
    print(f"  language: {result.get('language')}")
    print(f"  text[:100]: {result['text'][:100]}")

    segs = result.get("segments", [])
    has_words = bool(segs) and bool(segs[0].get("words"))
    print(f"  has word_timestamps: {has_words}")
    if has_words:
        first_words = segs[0]["words"][:3]
        print(f"  first 3 words: {first_words}")
    return elapsed, result["text"], has_words


def bench_faster_whisper():
    print("\n[3] faster-whisper (CPU int8)")
    from faster_whisper import WhisperModel

    t0 = time.time()
    model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    print(f"  load: {time.time() - t0:.2f}s")

    t0 = time.time()
    segments, info = model.transcribe(AUDIO_PATH, word_timestamps=True)
    segments = list(segments)  # generator → list
    elapsed = time.time() - t0
    print(f"  transcribe: {elapsed:.2f}s")
    print(f"  language: {info.language}")

    text = " ".join(s.text for s in segments)
    print(f"  text[:100]: {text[:100]}")

    has_words = bool(segments) and bool(segments[0].words)
    print(f"  has word_timestamps: {has_words}")
    if has_words:
        first_words = [(w.word, w.start, w.end) for w in segments[0].words[:3]]
        print(f"  first 3 words: {first_words}")
    return elapsed, text, has_words


def main():
    print("=" * 70)
    print(f"Whisper 后端性能对比 — model={MODEL_SIZE}, audio={AUDIO_PATH}")
    print("=" * 70)

    results = {}

    try:
        t, text, has_w = bench_openai_whisper()
        results["openai"] = (t, text, has_w)
    except Exception as e:
        print(f"  openai/whisper 失败: {e}")

    try:
        t, text, has_w = bench_mlx_whisper()
        results["mlx"] = (t, text, has_w)
    except Exception as e:
        print(f"  mlx-whisper 失败: {e}")
        import traceback; traceback.print_exc()

    try:
        t, text, has_w = bench_faster_whisper()
        results["faster"] = (t, text, has_w)
    except Exception as e:
        print(f"  faster-whisper 失败: {e}")

    # 汇总
    print("\n" + "=" * 70)
    print("汇总")
    print("=" * 70)
    print(f"{'后端':<20} {'时间(s)':<12} {'word_ts':<12}")
    print("-" * 70)
    for name, (t, _, has_w) in results.items():
        print(f"{name:<20} {t:<12.2f} {('YES' if has_w else 'NO'):<12}")

    if "openai" in results:
        baseline = results["openai"][0]
        print(f"\n相对 openai/whisper 加速比:")
        for name, (t, _, _) in results.items():
            if name != "openai":
                print(f"  {name}: {baseline / t:.2f}x")

    # 决策
    print("\n" + "=" * 70)
    print("推荐")
    print("=" * 70)
    if "mlx" in results and results["mlx"][2]:
        if "openai" not in results or results["mlx"][0] <= results["openai"][0] / 1.5:
            print("→ 用 mlx-whisper (速度好且 word_timestamps 完整)")
        else:
            print("→ mlx-whisper 速度未达预期，建议看 faster-whisper")
    elif "faster" in results and results["faster"][2]:
        print("→ 用 faster-whisper (mlx 不可用或缺少 word_timestamps)")
    else:
        print("→ 没有合适的后端，需要排查")


if __name__ == "__main__":
    main()
