"""测试 LangChain 翻译模块"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.translator import Translator


def test_translate_english():
    """测试：英语翻译"""
    translator = Translator()
    result = translator.translate(
        "Tell me about a time when you had to deal with a difficult colleague.",
        source_language="en",
    )
    print(f"英语翻译测试:")
    print(f"  原文: {result['original']}")
    print(f"  翻译: {result['translation']}")
    assert result["translation"]


def test_translate_german():
    """测试：德语翻译"""
    translator = Translator()
    result = translator.translate(
        "Erzählen Sie mir von Ihren Stärken und Schwächen.",
        source_language="de",
    )
    print(f"德语翻译测试:")
    print(f"  原文: {result['original']}")
    print(f"  翻译: {result['translation']}")
    assert result["translation"]


def test_translate_empty():
    """测试：空文本"""
    translator = Translator()
    result = translator.translate("")
    print(f"空文本测试: translation='{result['translation']}'")
    assert result["translation"] == ""


async def test_translate_async():
    """测试：异步翻译"""
    translator = Translator()
    result = await translator.translate_async(
        "What is your greatest strength?", source_language="en"
    )
    print(f"异步翻译测试:")
    print(f"  原文: {result['original']}")
    print(f"  翻译: {result['translation']}")
    assert result["translation"]


if __name__ == "__main__":
    print("=" * 50)
    print("MIMI 翻译模块测试 (LangChain + Gemini)")
    print("=" * 50)
    print("注意：需要设置 GOOGLE_API_KEY 环境变量\n")

    print("--- 测试空文本 ---")
    test_translate_empty()

    print("\n--- 测试英语翻译 ---")
    test_translate_english()

    print("\n--- 测试德语翻译 ---")
    test_translate_german()

    print("\n--- 测试异步翻译 ---")
    asyncio.run(test_translate_async())

    print("\n所有测试完成!")
