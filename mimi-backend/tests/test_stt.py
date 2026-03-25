"""测试 Whisper STT 模块"""

import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.stt import SpeechToText


def test_stt_with_silence():
    """测试：静音输入应返回空文本"""
    stt = SpeechToText()
    # 生成 3 秒静音 (16kHz, float32)
    silence = np.zeros(16000 * 3, dtype=np.float32)
    result = stt.transcribe_audio(silence)
    print(f"静音测试结果: text='{result['text']}', language='{result['language']}'")
    assert isinstance(result["text"], str)


def test_stt_with_audio_file():
    """测试：用音频文件测试转写（需要提供测试文件）"""
    test_file = Path(__file__).parent / "test_audio.wav"
    if not test_file.exists():
        print(f"跳过：测试音频文件不存在 ({test_file})")
        print("可以放一个英语或德语的 .wav 文件到 tests/test_audio.wav 来测试")
        return

    stt = SpeechToText()
    result = stt.transcribe_file(str(test_file))
    print(f"文件转写结果:")
    print(f"  语言: {result['language']}")
    print(f"  文本: {result['text']}")
    print(f"  片段数: {len(result['segments'])}")
    for seg in result["segments"]:
        print(f"    [{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}")


def test_stt_model_loading():
    """测试：模型能正常加载"""
    stt = SpeechToText()
    model = stt.load_model()
    assert model is not None
    print(f"模型加载成功: {stt.model_size}")


if __name__ == "__main__":
    print("=" * 50)
    print("MIMI STT 模块测试")
    print("=" * 50)

    print("\n--- 测试模型加载 ---")
    test_stt_model_loading()

    print("\n--- 测试静音输入 ---")
    test_stt_with_silence()

    print("\n--- 测试音频文件 ---")
    test_stt_with_audio_file()

    print("\n所有测试完成!")
