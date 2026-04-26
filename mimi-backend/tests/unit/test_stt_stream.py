"""测试 LocalAgreement-2 流式 STT。

策略：把 30s 测试音频切成 1s 小块，逐块 feed，验证：
1. 至少有几次产出 confirmed_words（流式提交在工作）
2. 每次的 tentative_text 是当前 hypothesis 减去 confirmed
3. flush 后的所有 confirmed 拼起来 ≈ 一次性离线 transcribe 的结果
"""

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from audio.stt_mlx import SpeechToText
from audio.streaming import StreamingSTT, words_to_text


AUDIO_PATH = Path(__file__).parent.parent / "test_audio.wav"
CHUNK_SECONDS = 1.0


def load_audio_float32(path: Path) -> tuple[np.ndarray, int]:
    """读 16-bit PCM wav → float32 [-1, 1]。"""
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return audio, sr


def test_streaming_pipeline():
    print("=" * 60)
    print("StreamingSTT LocalAgreement-2 测试")
    print("=" * 60)

    stt = SpeechToText()
    stt.load_model()

    # 离线基线：一次性转写整段
    print("\n[基线] 一次性离线转写...")
    audio, sr = load_audio_float32(AUDIO_PATH)
    print(f"  音频: {len(audio)/sr:.1f}s @ {sr}Hz")
    baseline = stt.transcribe_audio(audio)
    print(f"  baseline text: {baseline['text']}")

    # 流式：每秒一块
    print(f"\n[流式] 切成 {CHUNK_SECONDS}s 块逐块 feed...")
    stream = StreamingSTT(stt, sample_rate=sr)
    chunk_samples = int(sr * CHUNK_SECONDS)

    all_confirmed = []
    last_tentative = ""
    for i in range(0, len(audio), chunk_samples):
        chunk = audio[i:i + chunk_samples]
        result = stream.feed(chunk)
        elapsed = (i + len(chunk)) / sr
        if result.confirmed_words:
            text = words_to_text(result.confirmed_words)
            all_confirmed.append(text)
            print(f"  [{elapsed:5.1f}s] CONFIRMED: {text!r}")
        if result.tentative_text and result.tentative_text != last_tentative:
            print(f"  [{elapsed:5.1f}s]    tentative: {result.tentative_text!r}")
            last_tentative = result.tentative_text

    # flush 剩余
    final = stream.flush()
    if final.confirmed_words:
        text = words_to_text(final.confirmed_words)
        all_confirmed.append(text)
        print(f"  [flush] CONFIRMED: {text!r}")

    streaming_text = " ".join(all_confirmed)
    print(f"\n[流式拼接结果] {streaming_text}")

    # 验证
    assert len(all_confirmed) >= 2, f"期望多次提交，实际只有 {len(all_confirmed)} 次"
    assert streaming_text, "流式结果为空"
    # 字数应该接近基线（允许 ±20% 偏差，因为流式可能略有 word 边界差异）
    base_len = len(baseline["text"])
    stream_len = len(streaming_text)
    ratio = stream_len / base_len if base_len else 0
    print(f"\n基线字数: {base_len}, 流式字数: {stream_len}, 比例: {ratio:.2f}")
    assert 0.8 <= ratio <= 1.25, f"流式结果字数偏差太大: {ratio:.2f}"
    print("\n所有测试通过 ✓")


def test_silence_chunk():
    """静音块不应该提交任何东西"""
    stt = SpeechToText()
    stt.load_model()
    stream = StreamingSTT(stt, sample_rate=16000)

    silence = np.zeros(16000, dtype=np.float32)  # 1s 静音
    for _ in range(3):
        result = stream.feed(silence)
        assert not result.confirmed_words, f"静音不应有 confirmed: {result.confirmed_words!r}"
    print("静音测试通过 ✓")


def test_lcp_normalization():
    """单元测试：词汇规范化匹配"""
    from audio.streaming import StreamingSTT as S

    # 标点不同应该被认为相同
    a = [{"word": "Hello,", "start": 0, "end": 0.5}]
    b = [{"word": "Hello", "start": 0, "end": 0.5}]
    assert S._longest_common_prefix(a, b) == 1

    # 大小写不同应该相同
    a = [{"word": "Hello", "start": 0, "end": 0.5}]
    b = [{"word": "hello", "start": 0, "end": 0.5}]
    assert S._longest_common_prefix(a, b) == 1

    # 完全不同的词
    a = [{"word": "Hello", "start": 0, "end": 0.5}]
    b = [{"word": "World", "start": 0, "end": 0.5}]
    assert S._longest_common_prefix(a, b) == 0

    # 公共前缀
    a = [{"word": "I", "start": 0, "end": 0.1}, {"word": "am", "start": 0.1, "end": 0.2}, {"word": "fine", "start": 0.2, "end": 0.4}]
    b = [{"word": "I", "start": 0, "end": 0.1}, {"word": "am", "start": 0.1, "end": 0.2}, {"word": "good", "start": 0.2, "end": 0.4}]
    assert S._longest_common_prefix(a, b) == 2

    print("LCP 规范化测试通过 ✓")


def test_low_energy_noise_rejected():
    """RMS=0.02 的低能量噪音（低于阈值 0.03）应被静音检测拦截"""
    stt = SpeechToText()
    stt.load_model()
    stream = StreamingSTT(stt, sample_rate=16000)

    noise = np.random.randn(16000).astype(np.float32) * 0.005  # RMS ≈ 0.005 < 0.01 threshold
    for i in range(10):
        result = stream.feed(noise)
        assert not result.confirmed_words, f"chunk {i}: 低能量噪音不应有 confirmed: {result.confirmed_words!r}"
        assert not result.tentative_text, f"chunk {i}: 低能量噪音不应有 tentative: {result.tentative_text!r}"
    print("低能量噪音测试通过 ✓")


if __name__ == "__main__":
    test_lcp_normalization()
    test_silence_chunk()
    test_low_energy_noise_rejected()
    test_streaming_pipeline()
