"""分句诊断脚本 — 三层对比定位分句不准的根因。

Layer 1: Whisper 离线基线（一次性转写，最佳标点）
Layer 2: LocalAgreement-2 流式输出（逐块 feed，观察标点丢失）
Layer 3: SentenceSegmenter 分句结果（观察切分效果）

跑法：
    cd mimi-backend
    /Users/marlon/anaconda3/envs/mimi/bin/python tests/test_segmentation_diagnosis.py
"""

import re
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from audio.stt_mlx import SpeechToText
from audio.streaming import StreamingSTT
from conversation.history import SharedHistory
from conversation.segmenter import SentenceSegmenter

AUDIO_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "test_audio.wav"
CHUNK_SECONDS = 1.0
SENTENCE_ENDINGS = {'.', '?', '!'}


def load_audio(path):
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0, sr


def split_by_punctuation(text):
    """按 .?! 切句（和 SentenceSegmenter 同逻辑）"""
    sentences = []
    current = ""
    for ch in text:
        current += ch
        if ch in SENTENCE_ENDINGS:
            s = current.strip()
            if s:
                sentences.append(s)
            current = ""
    if current.strip():
        sentences.append(current.strip())
    return sentences


def find_punctuation_positions(text):
    """返回所有 .?! 的字符位置"""
    return [i for i, ch in enumerate(text) if ch in SENTENCE_ENDINGS]


def find_repeated_words(text):
    """找连续重复词（如 "not Not", "as as"）"""
    words = text.split()
    repeats = []
    for i in range(len(words) - 1):
        if words[i].lower().rstrip(".,!?;:") == words[i + 1].lower().rstrip(".,!?;:"):
            repeats.append(f'"{words[i]} {words[i+1]}" @word:{i}')
    return repeats


def layer1_offline_baseline(stt, audio):
    """Layer 1: Whisper 离线基线"""
    print("=" * 70)
    print("Layer 1: Whisper 离线基线（一次性转写，最佳标点）")
    print("=" * 70)

    result = stt.transcribe_audio(audio)
    text = result["text"]
    sentences = split_by_punctuation(text)

    print(f"\n完整文本 ({len(text)} 字符):")
    print(f"  {text}")
    print(f"\n句子数: {len(sentences)}")
    for i, s in enumerate(sentences):
        print(f"  [{i+1}] ({len(s)}字符) {s}")

    return text, sentences


def layer2_streaming_output(stt, audio, sr):
    """Layer 2: LocalAgreement-2 流式输出"""
    print("\n" + "=" * 70)
    print("Layer 2: LocalAgreement-2 流式输出（1s 切块）")
    print("=" * 70)

    stream = StreamingSTT(stt, sample_rate=sr)
    chunk_samples = int(sr * CHUNK_SECONDS)

    all_confirmed = []
    all_confirmed_words = []
    buffer_lengths = []

    for i in range(0, len(audio), chunk_samples):
        chunk = audio[i:i + chunk_samples]
        elapsed = (i + len(chunk)) / sr

        buf_len = len(stream.buffer) / sr
        result = stream.feed(chunk)

        if result.confirmed_text:
            all_confirmed.append(result.confirmed_text)
            all_confirmed_words.append(list(result.confirmed_words))
            buffer_lengths.append(buf_len)
            print(f"  [{elapsed:5.1f}s] buf={buf_len:4.1f}s  CONFIRMED: {result.confirmed_text!r}")
        elif result.tentative_text:
            print(f"  [{elapsed:5.1f}s] buf={buf_len:4.1f}s  tentative: {result.tentative_text[:60]!r}...")

    # flush
    final = stream.flush()
    if final.confirmed_text:
        all_confirmed.append(final.confirmed_text)
        all_confirmed_words.append(list(final.confirmed_words))
        print(f"  [flush] CONFIRMED: {final.confirmed_text!r}")

    streaming_text = " ".join(all_confirmed)
    print(f"\n拼接结果 ({len(streaming_text)} 字符):")
    print(f"  {streaming_text}")

    # 统计
    repeats = find_repeated_words(streaming_text)
    avg_buf = sum(buffer_lengths) / len(buffer_lengths) if buffer_lengths else 0

    print(f"\n统计:")
    print(f"  confirmed 次数: {len(all_confirmed)}")
    print(f"  平均提交时 buffer 长度: {avg_buf:.1f}s")
    if repeats:
        print(f"  重复词 ({len(repeats)} 处): {repeats[:10]}")
    else:
        print(f"  重复词: 无")

    return streaming_text, all_confirmed, all_confirmed_words


def layer2_punctuation_compare(offline_text, streaming_text):
    """对比离线和流式的标点差异"""
    print("\n--- 标点对比 ---")
    offline_pos = find_punctuation_positions(offline_text)
    streaming_pos = find_punctuation_positions(streaming_text)

    print(f"  离线句号/问号/感叹号数量: {len(offline_pos)}")
    print(f"  流式句号/问号/感叹号数量: {len(streaming_pos)}")

    if offline_pos:
        loss_rate = 1 - len(streaming_pos) / len(offline_pos)
        print(f"  标点丢失率: {loss_rate:.0%}")


def layer3_segmentation(all_confirmed, all_confirmed_words):
    """Layer 3: SentenceSegmenter 分句结果（对比 add_text vs add_words）"""
    print("\n" + "=" * 70)
    print("Layer 3a: SentenceSegmenter.add_text (原方案，只看 .?!)")
    print("=" * 70)

    history_a = SharedHistory()
    seg_a = SentenceSegmenter("interviewer", history_a)
    all_sentences_a = []
    for confirmed in all_confirmed:
        completed = seg_a.add_text(confirmed, "en")
        for s in completed:
            all_sentences_a.append(s["text"])
            print(f"  [句子] ({len(s['text'])}字符) {s['text']}")
    flushed = seg_a.flush()
    for s in flushed:
        all_sentences_a.append(s["text"])
        print(f"  [flush] ({len(s['text'])}字符) {s['text']}")

    print("\n" + "=" * 70)
    print("Layer 3b: SentenceSegmenter.add_words (新方案，停顿 >0.5s 也切)")
    print("=" * 70)

    history_b = SharedHistory()
    seg_b = SentenceSegmenter("interviewer", history_b)
    all_sentences_b = []
    for confirmed_words in all_confirmed_words:
        completed = seg_b.add_words(confirmed_words, "en")
        for s in completed:
            all_sentences_b.append(s["text"])
            print(f"  [句子] ({len(s['text'])}字符) {s['text']}")
    flushed = seg_b.flush()
    for s in flushed:
        all_sentences_b.append(s["text"])
        print(f"  [flush] ({len(s['text'])}字符) {s['text']}")

    # 统计对比
    def stats(sentences, label):
        if not sentences:
            print(f"\n{label}: 无句子")
            return
        lengths = [len(s) for s in sentences]
        long_sentences = [s for s in sentences if len(s) > 100]
        print(f"\n{label}:")
        print(f"  总句数: {len(sentences)}")
        print(f"  句子长度: min={min(lengths)}, max={max(lengths)}, avg={sum(lengths)/len(lengths):.0f}")
        print(f"  长句(>100): {len(long_sentences)}")

    stats(all_sentences_a, "add_text 统计")
    stats(all_sentences_b, "add_words 统计")

    # 为保持后续代码兼容，返回新方案的结果
    all_sentences = all_sentences_b
    if all_sentences:
        lengths = [len(s) for s in all_sentences]
        long_sentences = [s for s in all_sentences if len(s) > 100]
        # 占位，保持下面的打印逻辑不报错
        print(f"\n(以下是 add_words 结果作为主结果)")
        print(f"  句子长度: min={min(lengths)}, max={max(lengths)}, avg={sum(lengths)/len(lengths):.0f}")
        if long_sentences:
            print(f"  超长句子 (>100字符): {len(long_sentences)} 个")
            for s in long_sentences:
                print(f"    ({len(s)}字符) {s[:80]}...")

    return all_sentences


def main():
    print("分句诊断脚本")
    print(f"音频: {AUDIO_PATH}")
    print(f"Chunk: {CHUNK_SECONDS}s")
    print()

    stt = SpeechToText()
    stt.load_model()
    audio, sr = load_audio(AUDIO_PATH)
    print(f"音频: {len(audio)/sr:.1f}s @ {sr}Hz\n")

    # Layer 1
    offline_text, offline_sentences = layer1_offline_baseline(stt, audio)

    # Layer 2
    streaming_text, all_confirmed, all_confirmed_words = layer2_streaming_output(stt, audio, sr)
    layer2_punctuation_compare(offline_text, streaming_text)

    # Layer 3
    streaming_sentences = layer3_segmentation(all_confirmed, all_confirmed_words)

    # 总结
    print("\n" + "=" * 70)
    print("总结")
    print("=" * 70)
    print(f"  离线句子数: {len(offline_sentences)}")
    print(f"  流式句子数: {len(streaming_sentences)}")
    print(f"  差异: {len(streaming_sentences) - len(offline_sentences):+d}")


if __name__ == "__main__":
    main()
