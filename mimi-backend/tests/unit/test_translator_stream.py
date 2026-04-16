"""测试 Translator.translate_stream — 流式翻译 token 产出"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from translation.langchain_translator import Translator


async def test_stream_yields_chunks():
    """测试：长文本翻译应该产出多个 chunk，验证流式确实在工作

    注意：Gemini 的流式 API 返回的是较大的文本块（~50 字符），不是 token 级。
    短句可能只有 1 个 chunk；长句应该有 ≥2 个。
    """
    translator = Translator()
    long_text = (
        "Could you walk me through your experience designing and implementing "
        "distributed systems at scale? I am particularly interested in hearing "
        "about how you approached challenges like service discovery, load "
        "balancing, fault tolerance, and observability across multiple data centers."
    )
    chunks = []
    async for delta in translator.translate_stream(long_text, source_language="en"):
        chunks.append(delta)
        print(f"[chunk #{len(chunks)}] {delta!r}")

    full = "".join(chunks).strip()
    print(f"\n拼接结果 ({len(full)} 字): {full}")
    assert len(chunks) >= 2, f"长文本期望多个 chunk，实际只有 {len(chunks)} 个"
    assert full, "拼接后翻译为空"


async def test_stream_short_text():
    """测试：短文本至少产出 1 个 chunk"""
    translator = Translator()
    chunks = []
    async for delta in translator.translate_stream(
        "Hello, how are you?", source_language="en"
    ):
        chunks.append(delta)
    assert len(chunks) >= 1
    assert "".join(chunks).strip()


async def test_stream_empty_text():
    """测试：空文本应该产出零个 chunk"""
    translator = Translator()
    chunks = []
    async for delta in translator.translate_stream("", source_language="en"):
        chunks.append(delta)
    print(f"空文本测试: chunks={len(chunks)}")
    assert len(chunks) == 0


async def test_stream_with_context():
    """测试：带上下文的流式翻译"""
    translator = Translator()
    context = (
        "[Interviewer] We use Kubernetes for orchestration.\n"
        "[Me] I have hands-on experience with that."
    )
    chunks = []
    async for delta in translator.translate_stream(
        "How would you debug a pod stuck in CrashLoopBackOff?",
        source_language="en",
        context=context,
    ):
        chunks.append(delta)
    full = "".join(chunks).strip()
    print(f"上下文流式: {full}")
    assert full


if __name__ == "__main__":
    print("=" * 50)
    print("MIMI 流式翻译测试")
    print("=" * 50)
    print("注意：需要设置 GOOGLE_API_KEY 环境变量\n")

    print("--- 测试 yield 多个 chunk ---")
    asyncio.run(test_stream_yields_chunks())

    print("\n--- 测试空文本 ---")
    asyncio.run(test_stream_empty_text())

    print("\n--- 测试带上下文 ---")
    asyncio.run(test_stream_with_context())

    print("\n所有测试完成!")
