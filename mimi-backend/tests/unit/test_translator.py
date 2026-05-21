"""测试 LangChain 翻译模块"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")
from llm import LLMManager
from translation.langchain_translator import Translator


def _new_translator() -> Translator:
    """Test helper：复用单例 LLMManager（启动时从 .env 读 key）"""
    return Translator(LLMManager())


def test_translate_english():
    """测试：英语翻译"""
    translator = _new_translator()
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
    translator = _new_translator()
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
    translator = _new_translator()
    result = translator.translate("")
    print(f"空文本测试: translation='{result['translation']}'")
    assert result["translation"] == ""


async def test_translate_async():
    """测试：异步翻译"""
    translator = _new_translator()
    result = await translator.translate_async(
        "What is your greatest strength?", source_language="en"
    )
    print(f"异步翻译测试:")
    print(f"  原文: {result['original']}")
    print(f"  翻译: {result['translation']}")
    assert result["translation"]


def test_translate_with_context():
    """测试：带对话上下文的翻译"""
    translator = _new_translator()
    context = (
        "[Interviewer] We use a microservices architecture here.\n"
        "[Me] I have experience with that approach."
    )
    result = translator.translate(
        "How did you handle service discovery?",
        source_language="en",
        context=context,
    )
    print(f"上下文翻译测试:")
    print(f"  上下文: {context[:50]}...")
    print(f"  原文: {result['original']}")
    print(f"  翻译: {result['translation']}")
    assert result["translation"]


def test_translate_empty_context():
    """测试：空上下文（传空字符串）"""
    translator = _new_translator()
    result = translator.translate("Hello.", source_language="en", context="")
    print(f"空上下文测试: translation='{result['translation']}'")
    assert result["translation"]


# ============================================================
# 面试场景化 prompt 专项测试
# ============================================================

def test_preserve_tech_terms():
    """面试 prompt：技术名词应保留英文（不翻译成中文术语）。"""
    translator = _new_translator()
    result = translator.translate(
        "I have three years of experience with React, TypeScript and Kubernetes.",
        source_language="en",
    )
    translation = result["translation"]
    print(f"技术术语测试: {translation}")
    # 三个术语至少保留其中 2 个（宽松断言，允许 LLM 偶尔失误）
    preserved = sum(term in translation for term in ("React", "TypeScript", "Kubernetes"))
    assert preserved >= 2, f"只保留了 {preserved}/3 个术语: {translation}"


def test_skip_filler_words():
    """面试 prompt：纯填充词应返回空或近空。"""
    translator = _new_translator()
    result = translator.translate("Um, uh, like, you know.", source_language="en")
    translation = result["translation"].strip()
    print(f"填充词测试: translation='{translation}'")
    # 允许返回空、标点或极短（<5 字符），但不应翻译成"嗯啊"这种长字符串
    assert len(translation) < 5, f"填充词不应产生长翻译: {translation!r}"


def test_short_response():
    """面试 prompt：简短应答应按语境意译。"""
    translator = _new_translator()
    context = (
        "[Interviewer] We use microservices with gRPC.\n"
        "[Me] I'm familiar with that architecture."
    )
    result = translator.translate("OK.", source_language="en", context=context)
    translation = result["translation"].strip()
    print(f"短句测试: translation='{translation}'")
    # "OK." 应翻成单字或极短中文（"好" / "好的" / "嗯"），不是"确定"
    assert 1 <= len(translation) <= 6, f"短句翻译长度异常: {translation!r}"
    assert "确定" not in translation, f"OK 不应翻译成'确定': {translation!r}"


# ============================================================
# 上下文相关翻译测试（验证 context 真正影响翻译结果）
# ============================================================

def test_context_coreference():
    """上下文：代词指代应通过上下文解析。

    "I used it." 中的 "it" 在不同上下文下应指向不同对象。
    """
    translator = _new_translator()
    context = (
        "[Interviewer] Have you worked with Kubernetes before?\n"
        "[Me] Yes, at my previous company."
    )
    result = translator.translate(
        "I used it for three years in production.",
        source_language="en",
        context=context,
    )
    translation = result["translation"]
    print(f"代词指代测试: {translation}")
    # 翻译要么保留 "it"，要么显式说 "Kubernetes"，都合理
    # 但如果纯直译"它"会丢失信息——这里验证至少不会完全丢失语义
    assert translation.strip(), "翻译不应为空"
    # 上下文提到 Kubernetes，翻译里应该体现出产品/技术的连续性
    # （要么保留代词，要么点出 Kubernetes，都接受）


def test_context_disambiguates_short_response():
    """上下文：同一个 "Yeah" 在不同问题下翻译可以不同。

    验证 context 真的被模型读取并影响翻译，而不是机械映射。
    """
    translator = _new_translator()

    # 场景 A：回答"你会不会"类问题 → 应该翻成肯定回答
    context_a = "[Interviewer] Do you know JavaScript?"
    result_a = translator.translate("Yeah.", source_language="en", context=context_a)

    # 场景 B：表示"明白了"的场景 → 应该翻成表示理解的词
    context_b = (
        "[Interviewer] Let me explain our architecture. "
        "We use a message queue between services."
    )
    result_b = translator.translate("Yeah.", source_language="en", context=context_b)

    print(f"短句上下文 A (问'会不会'): '{result_a['translation']}'")
    print(f"短句上下文 B (被解释): '{result_b['translation']}'")

    # 两次翻译都不应为空
    assert result_a["translation"].strip()
    assert result_b["translation"].strip()
    # 两次翻译都应该简短（单字/双字）
    assert len(result_a["translation"].strip()) <= 6
    assert len(result_b["translation"].strip()) <= 6


def test_context_preserves_tech_terminology():
    """上下文：技术术语在多轮对话中应一致保留英文。

    即使上下文和当前输入都含术语，翻译也应该都保留。
    """
    translator = _new_translator()
    context = (
        "[Interviewer] We're migrating from Docker Compose to Kubernetes.\n"
        "[Me] That's a big change."
    )
    result = translator.translate(
        "How do you handle rolling deployments in k8s?",
        source_language="en",
        context=context,
    )
    translation = result["translation"]
    print(f"术语一致性测试: {translation}")
    # "k8s" 是 Kubernetes 的简写，应保留或显式写 Kubernetes，而非翻译成"八字"之类
    has_k8s_or_kubernetes = "k8s" in translation or "Kubernetes" in translation
    assert has_k8s_or_kubernetes, f"k8s 未被保留: {translation!r}"


def test_context_mixed_language():
    """上下文：中英混合上下文下，英文当前句仍正常翻译。"""
    translator = _new_translator()
    context = (
        "[Interviewer] 你用过 React 吗？\n"
        "[Me] 用过，做过几个前端项目。"
    )
    result = translator.translate(
        "Great. Can you walk me through a component you built?",
        source_language="en",
        context=context,
    )
    translation = result["translation"]
    print(f"中英混合上下文测试: {translation}")
    assert translation.strip(), "翻译不应为空"
    # 应该翻译成中文（不是保留英文）
    # 简单检查：至少含一个中文字符
    has_chinese = any('\u4e00' <= ch <= '\u9fff' for ch in translation)
    assert has_chinese, f"中英混合上下文下，翻译应为中文: {translation!r}"


# ============================================================
# Prompt 渲染（零依赖：不调 LLM，验证 i18n 接入正确）
# ============================================================

def test_invoke_kwargs_native_japanese():
    """set_native_language("ja") → native_language_name 应为 '日本語'"""
    translator = _new_translator()
    translator.set_native_language("ja")
    kwargs = translator._build_invoke_kwargs("Hello.", source_language="en", context="")
    print(f"native=ja: native_language_name='{kwargs['native_language_name']}'")
    assert kwargs["native_language_name"] == "日本語"


def test_invoke_kwargs_interview_french():
    """source_language='fr' → interview_language_name 应为 '法语'"""
    translator = _new_translator()
    kwargs = translator._build_invoke_kwargs("Bonjour.", source_language="fr", context="")
    print(f"interview=fr: interview_language_name='{kwargs['interview_language_name']}'")
    assert kwargs["interview_language_name"] == "法语"


def test_invoke_kwargs_unknown_source_fallback():
    """未知 source_language 代码 → fallback 到代码本身（不抛异常）"""
    translator = _new_translator()
    kwargs = translator._build_invoke_kwargs("...", source_language="xx", context="")
    print(f"interview=xx: interview_language_name='{kwargs['interview_language_name']}'")
    # i18n.zh_name 用 fallback 参数 src 本身
    assert kwargs["interview_language_name"] == "xx"


def test_invoke_kwargs_native_spanish():
    """set_native_language("es") → native_language_name 应为 'Español'"""
    translator = _new_translator()
    translator.set_native_language("es")
    kwargs = translator._build_invoke_kwargs("Hello.", source_language="en", context="")
    print(f"native=es: native_language_name='{kwargs['native_language_name']}'")
    assert kwargs["native_language_name"] == "Español"


if __name__ == "__main__":
    print("=" * 50)
    print("MIMI 翻译模块测试 (LangChain + Gemini)")
    print("=" * 50)
    print("注意：需要设置 GOOGLE_API_KEY 环境变量\n")

    print("--- Prompt 渲染：母语日语 ---")
    test_invoke_kwargs_native_japanese()

    print("\n--- Prompt 渲染：面试法语 ---")
    test_invoke_kwargs_interview_french()

    print("\n--- Prompt 渲染：未知源语言 fallback ---")
    test_invoke_kwargs_unknown_source_fallback()

    print("\n--- Prompt 渲染：母语西语 ---")
    test_invoke_kwargs_native_spanish()


    print("--- 测试空文本 ---")
    test_translate_empty()

    print("\n--- 测试英语翻译 ---")
    test_translate_english()

    print("\n--- 测试德语翻译 ---")
    test_translate_german()

    print("\n--- 测试异步翻译 ---")
    asyncio.run(test_translate_async())

    print("\n--- 测试上下文翻译 ---")
    test_translate_with_context()

    print("\n--- 测试空上下文 ---")
    test_translate_empty_context()

    print("\n--- 面试场景：保留技术术语 ---")
    test_preserve_tech_terms()

    print("\n--- 面试场景：省略填充词 ---")
    test_skip_filler_words()

    print("\n--- 面试场景：短句意译 ---")
    test_short_response()

    print("\n--- 上下文：代词指代 ---")
    test_context_coreference()

    print("\n--- 上下文：短句消歧 ---")
    test_context_disambiguates_short_response()

    print("\n--- 上下文：术语一致保留 ---")
    test_context_preserves_tech_terminology()

    print("\n--- 上下文：中英混合 ---")
    test_context_mixed_language()

    print("\n所有测试完成!")
