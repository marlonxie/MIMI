"""Intent LLM gate — 三层触发架构的第二层。

判定一句面试官发言是否值得给候选人生成回答建议。
输出 yes/no raw string（纯 bool，不需要结构化）。

成本：每次 ~50-80 input tokens + 1-3 output tokens，Gemini flash 约 $0.00005/call。
"""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from llm import LLMManager


_LANG_NAMES = {"en": "English", "de": "German"}


INTENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """判定面试官这句话是否值得给候选人生成回答建议。

回 yes 的情况：
- 明确的技术/行为面试问题（"Tell me about...", "How did you...", "Why...", "What would you..."）
- 要求详述/举例（"Can you give an example?", "Elaborate on...", "Walk me through..."）
- 让候选人发表观点/选择（"Which approach would you...?"）

回 no 的情况：
- 寒暄、打招呼、过渡语（"Hello", "Good to meet you", "Let's get started"）
- 确认/反馈语（"OK", "Got it", "Interesting", "I see", "That makes sense"）
- 面试官自己在解释/背景介绍（"So, our team uses Python", "We have about 50 engineers"）
- 口头 filler 和残句（"Um", "So...", "And then..."）

**只回答 `yes` 或 `no`，不要任何其他字符。**

面试语言：{interview_language}

最近对话（供上下文参考）：
{context}"""),
    ("human", "面试官刚说的：{text}"),
])


def _parse_yes_no(resp: str) -> bool:
    """稳健解析 LLM 输出。fail-safe 倾向放行。"""
    r = resp.strip().lower()
    if not r:
        return True
    if r.startswith("y") or r.startswith("是") or r.startswith("ja"):
        return True
    if r.startswith("n"):
        return False
    return True  # 异常输出 → 默认放行（宁可多触发不漏）


class IntentClassifier:
    """LLM 二分类器：face-value 面试发言 → 是否值得生成建议。

    懒就绪：构造时若 LLMManager 已有 key，立刻 build chain；否则 chain=None。
    `should_respond` 在 chain 未就绪时 fail-safe 返回 True（让 RAG 自己判，不阻塞流程）。
    """

    def __init__(self, llm_manager: LLMManager):
        self.manager = llm_manager
        self.llm = None
        self.chain = None
        self._try_build()

    def _try_build(self) -> None:
        self.llm = None
        self.chain = None
        if not self.manager.has_key():
            return
        try:
            self.llm = self.manager.make_llm(temperature=0)
            self.chain = INTENT_PROMPT | self.llm | StrOutputParser()
        except Exception as e:
            print(f"[intent] build failed: {e}")

    def rebuild(self) -> None:
        self._try_build()

    @property
    def is_ready(self) -> bool:
        return self.chain is not None

    async def should_respond(self, text: str, context: str, language: str) -> bool:
        if not self.is_ready:
            return True  # 未就绪 fail-safe 放行
        try:
            resp = await self.chain.ainvoke({
                "text": text,
                "context": context,
                "interview_language": _LANG_NAMES.get(language, "English"),
            })
            return _parse_yes_no(resp)
        except Exception as e:
            print(f"[intent] classifier 异常，默认放行: {e}")
            return True
