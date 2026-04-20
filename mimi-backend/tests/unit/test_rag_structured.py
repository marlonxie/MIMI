"""RAGEngine.generate_suggestion 三段式输出的烟雾测试。需要 GOOGLE_API_KEY 和 RAG 索引。

只验"能跑起来"+"输出包含 📌💡🗣️ 三段"，不验内容质量。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rag.engine import RAGEngine


async def _run():
    r = RAGEngine()
    result = await r.generate_suggestion(
        latest_text="Tell me about your distributed systems experience",
        interview_language="en",
        native_language="zh",
        conversation_context="",
    )
    suggestion = result["suggestion"]
    print("=== 生成内容 ===")
    print(suggestion)
    print("================")

    # 基本 schema 断言
    assert isinstance(suggestion, str) and suggestion.strip(), "suggestion 为空"
    assert isinstance(result["sources"], list), "sources 应为 list"

    # 三段 emoji 都出现
    assert "📌" in suggestion, "缺少 📌 问题理解段"
    assert "💡" in suggestion, "缺少 💡 要点段"
    assert "🗣️" in suggestion, "缺少 🗣️ 示例回答段"

    # 顺序应该是 📌 → 💡 → 🗣️
    pos_understanding = suggestion.index("📌")
    pos_keypoints = suggestion.index("💡")
    pos_sample = suggestion.index("🗣️")
    assert pos_understanding < pos_keypoints < pos_sample, \
        f"三段顺序错误: 📌@{pos_understanding}, 💡@{pos_keypoints}, 🗣️@{pos_sample}"


def test_bilingual_three_section_output():
    asyncio.run(_run())


if __name__ == "__main__":
    test_bilingual_three_section_output()
    print("\nRAG 双语三段输出测试通过")
