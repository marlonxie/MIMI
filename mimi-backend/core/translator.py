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


# 翻译 prompt 模板（带上下文）
TRANSLATE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是一个专业的翻译助手。根据对话上下文准确翻译。只返回翻译结果，不要解释、不要加引号。\n\n对话上下文：\n{context}"),
    ("human", "将以下{source_hint}文本翻译成中文：\n\n{text}"),
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
        self.target_language = translator_config["target_language"]

        # 创建 LLM 实例
        self.llm = _create_llm(self.provider, self.model_name, temperature=0.3)

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

    @staticmethod
    def _get_source_hint(source_language: str = None) -> str:
        if source_language:
            lang_map = {"en": "英语", "de": "德语"}
            return lang_map.get(source_language, source_language)
        return ""
