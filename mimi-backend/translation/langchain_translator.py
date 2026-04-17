"""LangChain 翻译模块 — 支持 Gemini / Claude / 其他 LLM 切换"""

import yaml
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 加载 .env 文件中的环境变量（GOOGLE_API_KEY 等）
load_dotenv(Path(__file__).parent.parent / ".env")


# 支持的 LLM provider 和对应的 LangChain 类
PROVIDER_MAP = {
    "gemini": {
        "module": "langchain_google_genai",
        "class": "ChatGoogleGenerativeAI",
        "env_key": "GOOGLE_API_KEY",
    },
    "claude": {
        "module": "langchain_anthropic",
        "class": "ChatAnthropic",
        "env_key": "ANTHROPIC_API_KEY",
    },
}


def _create_llm(provider: str, model: str, **kwargs):
    """根据 provider 动态加载对应的 LangChain Chat 模型"""
    import importlib

    if provider not in PROVIDER_MAP:
        raise ValueError(f"不支持的 provider: {provider}，可选: {list(PROVIDER_MAP.keys())}")

    info = PROVIDER_MAP[provider]
    mod = importlib.import_module(info["module"])
    cls = getattr(mod, info["class"])
    return cls(model=model, **kwargs)


# 翻译 prompt 模板（面试场景化）
# 设计原则基于翻译 prompt engineering 5 要素：
#   1. 角色分配（role） — "科技行业口译员"（限定领域）
#   2. 上下文（context） — 最近 N 句对话
#   3. 术语表（glossary） — 保留不翻译的技术名词 / 公司名 / 人名
#   4. 少样本示例（few-shot） — 填充词 / 短句 / 技术名词 / 双语混合
#   5. 约束（constraints） — 只返回译文、纯填充词返回空
TRANSLATE_SYSTEM = """你是资深的科技行业口译员，专门负责英语→中文的实时面试字幕翻译。

任务：将面试对话的英文片段翻译成自然流畅的中文字幕。

=== 翻译原则 ===

1. 保留原文的专有名词和技术术语：
   - 技术名词（React, TypeScript, Kubernetes, Docker, Python, JavaScript, AWS, LLM, API, SDK 等）→ 保留英文
   - 公司/产品名（Google, OpenAI, Y-Combinator, Claude, GPT-4 等）→ 保留英文
   - 人名 → 保留英文（除非是常见音译如"马斯克"）
   - 编程语法片段（useState, async/await, map.filter）→ 保留原样

2. 省略填充词和口语毛刺：
   - "uh", "um", "like", "you know", "I mean", "sort of", "kind of" → 不翻译
   - 重复词（"yes yes", "and and"）→ 保留一个即可
   - 自我纠正（"I went to—I mean, I worked at"）→ 翻译修正后的内容

3. 简短应答按语境意译：
   - "Yeah" / "Yes" / "Right" / "OK" / "Sure" / "Exactly" → 根据对话语气译为"嗯/对/好/没错/当然"
   - "Got it" / "Makes sense" / "Gotcha" → "明白/有道理/懂了"

4. 保持面试语气：
   - 面试官的话：礼貌、专业
   - 回答者的话：自信、简洁

5. 双语混合输入：
   - 如果原文已含中文，保留中文部分不动，只翻译英文部分

=== 输出约束 ===

- 只返回中文翻译，不要解释
- 不加引号、不加注释、不加"翻译如下"等前缀
- 如果原文仅是填充词（如 "uh, um."）→ 返回空字符串

=== 参考样例 ===

原文: Um, I would say I have like three years of experience with React and Node.js.
译文: 我有三年 React 和 Node.js 的经验。

原文: Yeah, yeah, for sure. We used Kubernetes for orchestration.
译文: 没问题。我们用 Kubernetes 做编排。

原文: Could you walk me through your experience with, uh, distributed systems?
译文: 能聊聊你在分布式系统方面的经验吗？

原文: OK.
译文: 好。

原文: You know JavaScript 吗？
译文: 你会 JavaScript 吗？

=== 对话上下文（最近几句） ===
{context}"""

TRANSLATE_HUMAN = "翻译这段{source_hint}：\n\n{text}"

TRANSLATE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", TRANSLATE_SYSTEM),
    ("human", TRANSLATE_HUMAN),
])


class Translator:
    """使用 LangChain LCEL 进行实时翻译，支持多 LLM 切换"""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        translator_config = config["translator"]
        self.provider = translator_config["provider"]
        self.model_name = translator_config["model"]
        # 用户母语 = 翻译输出语言（当前 prompt 硬编码英→中，切换其他 native 需同步改 prompt）
        self.native_language = config["user"]["native_language"]

        # 创建 LLM 实例
        # temperature=0：确定性输出。相同（text, context）产出相同翻译，用户体验更稳定
        self.llm = _create_llm(self.provider, self.model_name, temperature=0)

        # 构建 LCEL chain: prompt → llm → 解析为纯字符串
        self.chain = TRANSLATE_PROMPT | self.llm | StrOutputParser()

    def translate(self, text: str, source_language: str = None, context: str = "") -> dict:
        """
        同步翻译

        Args:
            text: 要翻译的文本
            source_language: 源语言代码 ("en", "de")，None 则自动检测
            context: 对话上下文（提高翻译准确性）

        Returns:
            {"original": str, "translation": str, "source_language": str}
        """
        if not text or not text.strip():
            return {
                "original": text,
                "translation": "",
                "source_language": source_language or "unknown",
            }

        source_hint = self._get_source_hint(source_language)
        translation = self.chain.invoke({
            "text": text, "source_hint": source_hint, "context": context or ""
        })

        return {
            "original": text,
            "translation": translation.strip(),
            "source_language": source_language or "auto",
        }

    async def translate_async(self, text: str, source_language: str = None, context: str = "") -> dict:
        """
        异步翻译（用于 WebSocket 服务）

        LangChain LCEL chain 原生支持 ainvoke
        """
        if not text or not text.strip():
            return {
                "original": text,
                "translation": "",
                "source_language": source_language or "unknown",
            }

        source_hint = self._get_source_hint(source_language)
        translation = await self.chain.ainvoke({
            "text": text, "source_hint": source_hint, "context": context or ""
        })

        return {
            "original": text,
            "translation": translation.strip(),
            "source_language": source_language or "auto",
        }

    async def translate_stream(self, text: str, source_language: str = None, context: str = ""):
        """
        流式翻译 — 逐 token 产出。yields str delta。

        LCEL chain `prompt | llm | StrOutputParser()` 原生支持 .astream()，
        每个 chunk 是字符串增量。空文本返回空生成器。
        """
        if not text or not text.strip():
            return

        source_hint = self._get_source_hint(source_language)
        async for chunk in self.chain.astream({
            "text": text, "source_hint": source_hint, "context": context or ""
        }):
            if chunk:
                yield chunk

    def set_native_language(self, language: str) -> None:
        """运行时切换翻译输出语言。

        注意：当前 TRANSLATE_SYSTEM prompt 硬编码为"英→中"。
        切到其他 native 语言需同步调整 prompt，否则翻译结果不变。

        Args:
            language: ISO 639-1 代码（"zh" / "en" / ...）
        """
        self.native_language = language

    @staticmethod
    def _get_source_hint(source_language: str = None) -> str:
        if source_language:
            lang_map = {"en": "英语", "de": "德语"}
            return lang_map.get(source_language, source_language)
        return ""
