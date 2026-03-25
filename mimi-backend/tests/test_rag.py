"""测试 RAG 全链路：对话管理 + 索引 + 检索 + 提示生成"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_conversation_manager():
    """测试对话管理器：分句、上下文窗口、触发检测"""
    from core.conversation import ConversationManager

    conv = ConversationManager(context_window_size=5)

    # 模拟 STT 输出（完整句子）
    result1 = {
        "text": "Tell me about your experience with machine learning.",
        "language": "en",
        "segments": [],
    }
    sentences = conv.add_transcription(result1, speaker="interviewer")
    assert len(sentences) == 1
    assert sentences[0]["text"] == "Tell me about your experience with machine learning."
    print(f"  分句测试 1: {sentences[0]['text'][:50]}... ✓")

    # 模拟不完整句子
    result2 = {"text": "I have worked on several", "language": "en", "segments": []}
    sentences = conv.add_transcription(result2, speaker="me")
    assert len(sentences) == 0  # pending 中，未输出
    print(f"  不完整句子: pending (未输出) ✓")

    # 补完句子
    result3 = {"text": "ML projects in production.", "language": "en", "segments": []}
    sentences = conv.add_transcription(result3, speaker="me")
    assert len(sentences) == 1
    assert "ML projects" in sentences[0]["text"]
    print(f"  补完句子: {sentences[0]['text'][:50]}... ✓")

    # 上下文窗口
    context = conv.get_context_window()
    assert "[Interviewer]" in context
    assert "[Me]" in context
    print(f"  上下文窗口:\n{context}")

    # 触发检测
    result4 = {
        "text": "Can you be more specific about the deep learning part?",
        "language": "en",
        "segments": [],
    }
    sentences = conv.add_transcription(result4, speaker="interviewer")
    # should_trigger_suggestion: 上一句是面试官，current_source 也是面试官
    assert conv.should_trigger_suggestion("interviewer") is True
    print(f"  触发检测: True ✓")

    # 获取面试官最近说的
    last = conv.get_last_interviewer_text()
    assert "specific" in last
    print(f"  面试官最近说的: {last[:60]}...")

    print("  对话管理器测试全部通过!")


def test_indexer():
    """测试文档索引"""
    from rag.indexer import RAGIndexer

    indexer = RAGIndexer()
    docs = indexer.load_documents()
    assert len(docs) > 0, "没有加载到文档"
    print(f"  加载了 {len(docs)} 个文档段")

    chunks = indexer.split_documents(docs)
    assert len(chunks) > 0
    print(f"  切分为 {len(chunks)} 个文本块")

    # 完整索引
    vs = indexer.index()
    assert vs is not None
    print("  索引完成!")


def test_rag_retrieval():
    """测试 RAG 检索相关性"""
    from rag.engine import RAGEngine

    engine = RAGEngine()

    # 测试检索
    docs = engine.retriever.invoke("machine learning experience")
    assert len(docs) > 0
    print(f"  检索到 {len(docs)} 个相关文档块")
    for i, doc in enumerate(docs):
        print(f"    [{i+1}] {doc.page_content[:80]}...")


def test_rag_suggestion():
    """测试 RAG 回答提示生成"""
    from rag.engine import RAGEngine

    engine = RAGEngine()

    conversation_context = (
        "[Interviewer] Welcome to the interview. Let's start with your background.\n"
        "[Me] Thank you. I'm a machine learning engineer with 3 years of experience.\n"
        "[Interviewer] Tell me about a challenging ML project you worked on."
    )

    result = engine.generate_suggestion_sync(
        latest_text="Tell me about a challenging ML project you worked on.",
        language="en",
        conversation_context=conversation_context,
    )

    print(f"  提示生成结果:")
    print(f"  来源: {result['sources']}")
    print(f"  建议:\n{result['suggestion']}")
    assert result["suggestion"]
    print("  RAG 提示生成测试通过!")


def test_translator_with_context():
    """测试带上下文的翻译"""
    from core.translator import Translator

    translator = Translator()

    context = (
        "[Interviewer] Tell me about your experience at TechCorp.\n"
        "[Me] I worked on the recommendation system there."
    )

    result = translator.translate(
        "Can you elaborate on the latency optimization?",
        source_language="en",
        context=context,
    )
    print(f"  带上下文翻译:")
    print(f"    原文: {result['original']}")
    print(f"    翻译: {result['translation']}")
    assert result["translation"]
    print("  上下文翻译测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("MIMI RAG 全链路测试")
    print("=" * 60)

    print("\n--- 1. 对话管理器测试 ---")
    test_conversation_manager()

    print("\n--- 2. 文档索引测试 ---")
    test_indexer()

    print("\n--- 3. RAG 检索测试 ---")
    test_rag_retrieval()

    print("\n--- 4. RAG 提示生成测试 ---")
    test_rag_suggestion()

    print("\n--- 5. 上下文翻译测试 ---")
    test_translator_with_context()

    print("\n" + "=" * 60)
    print("所有测试完成!")
    print("=" * 60)
