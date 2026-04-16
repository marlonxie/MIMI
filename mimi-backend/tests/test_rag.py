"""测试 RAG 全链路：对话管理 + 索引 + 检索 + 提示生成"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================
# 对话管理器测试
# ============================

def test_sentence_segmentation():
    """测试：按标点分句"""
    from core.conversation import ConversationManager
    conv = ConversationManager()

    result = {"text": "Hello. How are you? I'm fine!", "language": "en", "segments": []}
    sentences = conv.add_transcription(result, speaker="interviewer")
    assert len(sentences) == 3
    assert sentences[0]["text"] == "Hello."
    assert sentences[1]["text"] == "How are you?"
    assert sentences[2]["text"] == "I'm fine!"
    print(f"  分句测试: 3 句 ✓")


def test_pending_buffer():
    """测试：不完整句子暂存 pending，补完后输出"""
    from core.conversation import ConversationManager
    conv = ConversationManager()

    # 不完整句子
    result1 = {"text": "I have worked on several", "language": "en", "segments": []}
    sentences = conv.add_transcription(result1, speaker="me")
    assert len(sentences) == 0
    print(f"  pending 暂存: 0 句输出 ✓")

    # 补完句子
    result2 = {"text": "ML projects in production.", "language": "en", "segments": []}
    sentences = conv.add_transcription(result2, speaker="me")
    assert len(sentences) == 1
    assert "ML projects" in sentences[0]["text"]
    print(f"  pending 补完: {sentences[0]['text'][:50]}... ✓")


def test_speaker_switch_flushes_pending():
    """测试：说话人切换时自动 flush pending"""
    from core.conversation import ConversationManager
    conv = ConversationManager()

    # 面试官说了不完整的句子
    result1 = {"text": "Tell me about your", "language": "en", "segments": []}
    conv.add_transcription(result1, speaker="interviewer")
    assert conv.pending_text == "Tell me about your"

    # 我开始说话 → 面试官的 pending 被强制输出
    result2 = {"text": "Sure, I worked on ML.", "language": "en", "segments": []}
    sentences = conv.add_transcription(result2, speaker="me")
    # 应该有 2 句：flush 的面试官句子 + 我的完整句子
    assert len(sentences) == 2
    assert sentences[0]["speaker"] == "interviewer"
    assert sentences[0]["text"] == "Tell me about your"
    assert sentences[1]["speaker"] == "me"
    print(f"  说话人切换 flush: {len(sentences)} 句 ✓")


def test_flush():
    """测试：手动 flush pending"""
    from core.conversation import ConversationManager
    conv = ConversationManager()

    result = {"text": "I have worked on", "language": "en", "segments": []}
    conv.add_transcription(result, speaker="me")
    assert conv.pending_text != ""

    flushed = conv.flush()
    assert len(flushed) == 1
    assert flushed[0]["text"] == "I have worked on"
    assert conv.pending_text == ""
    print(f"  flush: '{flushed[0]['text']}' ✓")


def test_flush_empty():
    """测试：空 pending flush"""
    from core.conversation import ConversationManager
    conv = ConversationManager()
    flushed = conv.flush()
    assert len(flushed) == 0
    print(f"  flush 空 pending: 0 句 ✓")


def test_empty_text():
    """测试：空文本输入"""
    from core.conversation import ConversationManager
    conv = ConversationManager()

    result = {"text": "", "language": "en", "segments": []}
    sentences = conv.add_transcription(result, speaker="interviewer")
    assert len(sentences) == 0

    result2 = {"text": "   ", "language": "en", "segments": []}
    sentences = conv.add_transcription(result2, speaker="interviewer")
    assert len(sentences) == 0
    print(f"  空文本: 0 句 ✓")


def test_context_window():
    """测试：上下文窗口"""
    from core.conversation import ConversationManager
    conv = ConversationManager(context_window_size=5)

    conv.add_transcription({"text": "Question one.", "language": "en", "segments": []}, "interviewer")
    conv.add_transcription({"text": "Answer one.", "language": "en", "segments": []}, "me")
    conv.add_transcription({"text": "Question two.", "language": "en", "segments": []}, "interviewer")

    context = conv.get_context_window()
    assert "[Interviewer] Question one." in context
    assert "[Me] Answer one." in context
    assert "[Interviewer] Question two." in context
    print(f"  上下文窗口:\n{context}")

    # 限制窗口大小
    context_small = conv.get_context_window(n=2)
    lines = context_small.strip().split("\n")
    assert len(lines) == 2
    print(f"  窗口限制 n=2: {len(lines)} 行 ✓")


def test_interviewer_consecutive_sentences():
    """测试：面试官连续说多句，get_last_interviewer_text 返回全部"""
    from core.conversation import ConversationManager
    conv = ConversationManager()

    conv.add_transcription({"text": "I see you worked at TechCorp.", "language": "en", "segments": []}, "interviewer")
    conv.add_transcription({"text": "That's a great company.", "language": "en", "segments": []}, "interviewer")
    conv.add_transcription({"text": "What did you do there?", "language": "en", "segments": []}, "interviewer")

    last = conv.get_last_interviewer_text()
    assert "TechCorp" in last
    assert "great company" in last
    assert "What did you do" in last
    print(f"  面试官连续 3 句: {last[:60]}... ✓")


def test_get_last_interviewer_text_after_me():
    """测试：我说话后，get_last_interviewer_text 返回空"""
    from core.conversation import ConversationManager
    conv = ConversationManager()

    conv.add_transcription({"text": "Tell me about ML.", "language": "en", "segments": []}, "interviewer")
    conv.add_transcription({"text": "I worked on several projects.", "language": "en", "segments": []}, "me")

    last = conv.get_last_interviewer_text()
    assert last == ""  # 最后说话人是我，没有连续的面试官句子
    print(f"  我说话后面试官文本为空 ✓")


def test_has_new_interviewer_speech():
    """测试：检查新面试官发言"""
    from core.conversation import ConversationManager
    conv = ConversationManager()

    conv.add_transcription({"text": "First question.", "language": "en", "segments": []}, "interviewer")
    assert conv.has_new_interviewer_speech(0) is True
    assert conv.has_new_interviewer_speech(1) is False

    conv.add_transcription({"text": "My answer.", "language": "en", "segments": []}, "me")
    assert conv.has_new_interviewer_speech(1) is False  # 只有 me 的发言

    conv.add_transcription({"text": "Follow up.", "language": "en", "segments": []}, "interviewer")
    assert conv.has_new_interviewer_speech(2) is True
    print(f"  has_new_interviewer_speech ✓")


def test_export_transcript():
    """测试：导出对话记录"""
    from core.conversation import ConversationManager

    with tempfile.TemporaryDirectory() as tmpdir:
        conv = ConversationManager(export_path=tmpdir)
        conv.add_transcription({"text": "Hello.", "language": "en", "segments": []}, "interviewer")
        conv.add_transcription({"text": "Hi.", "language": "en", "segments": []}, "me")

        filepath = conv.export_transcript("test_export.json")
        assert Path(filepath).exists()

        with open(filepath) as f:
            data = json.load(f)
        assert data["turns"] == 2
        assert len(data["history"]) == 2
        assert data["history"][0]["speaker"] == "interviewer"
        assert data["history"][1]["speaker"] == "me"
        print(f"  导出: {filepath} ({data['turns']} turns) ✓")


# ============================
# RAG 索引 + 检索 + 提示测试
# ============================

def test_indexer():
    """测试：文档索引"""
    from rag.indexer import RAGIndexer

    indexer = RAGIndexer()
    docs = indexer.load_documents()
    assert len(docs) > 0, "没有加载到文档"
    print(f"  加载了 {len(docs)} 个文档段")

    chunks = indexer.split_documents(docs)
    assert len(chunks) > 0
    print(f"  切分为 {len(chunks)} 个文本块")

    vs = indexer.index()
    assert vs is not None
    print("  索引完成!")


def test_rag_retrieval():
    """测试：RAG 检索相关性"""
    from rag.engine import RAGEngine

    engine = RAGEngine()
    docs = engine.retriever.invoke("machine learning experience")
    assert len(docs) > 0
    print(f"  检索到 {len(docs)} 个相关文档块")
    for i, doc in enumerate(docs):
        print(f"    [{i+1}] {doc.page_content[:80]}...")


def test_rag_suggestion():
    """测试：RAG 回答提示生成"""
    from rag.engine import RAGEngine

    engine = RAGEngine()

    conversation_context = (
        "[Interviewer] Welcome to the interview.\n"
        "[Me] Thank you.\n"
        "[Interviewer] Tell me about a challenging ML project you worked on."
    )

    result = engine.generate_suggestion_sync(
        latest_text="Tell me about a challenging ML project you worked on.",
        language="en",
        conversation_context=conversation_context,
    )

    print(f"  提示生成结果:")
    print(f"  来源: {result['sources']}")
    print(f"  建议:\n{result['suggestion'][:200]}...")
    assert result["suggestion"]
    assert "📌" in result["suggestion"] or "问题" in result["suggestion"]
    print("  RAG 提示生成测试通过!")


def test_translator_with_context():
    """测试：带上下文的翻译"""
    from translation.langchain_translator import Translator

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


def test_translator_empty_context():
    """测试：空上下文翻译"""
    from translation.langchain_translator import Translator

    translator = Translator()
    result = translator.translate("Hello.", source_language="en", context="")
    assert result["translation"]
    print(f"  空上下文翻译: '{result['translation']}' ✓")


# ============================
# 主入口
# ============================

if __name__ == "__main__":
    print("=" * 60)
    print("MIMI 全链路测试")
    print("=" * 60)

    print("\n--- 1. 对话管理器测试 ---")
    test_sentence_segmentation()
    test_pending_buffer()
    test_speaker_switch_flushes_pending()
    test_flush()
    test_flush_empty()
    test_empty_text()
    test_context_window()
    test_interviewer_consecutive_sentences()
    test_get_last_interviewer_text_after_me()
    test_has_new_interviewer_speech()
    test_export_transcript()

    print("\n--- 2. 文档索引测试 ---")
    test_indexer()

    print("\n--- 3. RAG 检索测试 ---")
    test_rag_retrieval()

    print("\n--- 4. RAG 提示生成测试 ---")
    test_rag_suggestion()

    print("\n--- 5. 翻译测试（上下文）---")
    test_translator_with_context()
    test_translator_empty_context()

    print("\n" + "=" * 60)
    print("所有测试完成!")
    print("=" * 60)
