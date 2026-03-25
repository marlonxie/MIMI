"""RAG 引擎 — 检索个人资料 + 生成回答提示"""

import yaml
from pathlib import Path
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

from core.translator import _create_llm

load_dotenv(Path(__file__).parent.parent / ".env")

LANG_MAP = {"en": "English", "de": "German"}

RAG_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是面试答案助手，旁听面试对话，帮助候选人组织回答。

输出格式：
1. 📌 问题理解（中文，1 句话概括面试官在问什么）
2. 💡 回答要点（中文，3-5 个要点提示）
3. 🗣️ 示例回答（用面试语言 {interview_language} 写，简洁易懂，可直接参考着说）

如果资料中没有直接相关信息，基于通用面试建议给出提示。

候选人资料：
{context}

对话历史：
{conversation}"""),
    ("human", "面试官最新说的：{latest_text}"),
])


def _format_docs(docs) -> str:
    return "\n\n".join(
        f"[来源: {doc.metadata.get('source', 'unknown')}]\n{doc.page_content}"
        for doc in docs
    )


class RAGEngine:
    """RAG 检索 + 回答提示生成"""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        rag_config = config["rag"]
        translator_config = config["translator"]
        chroma_path = str(Path(__file__).parent.parent / rag_config["chroma_path"])

        # Embedding 模型（与 indexer 相同）
        self.embeddings = HuggingFaceEmbeddings(
            model_name=rag_config["embedding_model"],
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

        # 加载已有的 ChromaDB 向量库
        self.vector_store = Chroma(
            collection_name="interview_materials",
            embedding_function=self.embeddings,
            persist_directory=chroma_path,
        )

        # Retriever
        self.retriever = self.vector_store.as_retriever(
            search_type=rag_config.get("search_type", "mmr"),
            search_kwargs={
                "k": rag_config.get("top_k", 3),
                "fetch_k": rag_config.get("top_k", 3) + 2,
            },
        )

        # LLM（复用 translator 的 provider 配置）
        self.llm = _create_llm(
            translator_config["provider"],
            translator_config["model"],
            temperature=0.5,
        )

        # LCEL chain
        self.chain = (
            {
                "context": (lambda x: x["latest_text"]) | self.retriever | _format_docs,
                "latest_text": lambda x: x["latest_text"],
                "conversation": lambda x: x.get("conversation", ""),
                "interview_language": lambda x: x.get("interview_language", "English"),
            }
            | RAG_PROMPT
            | self.llm
            | StrOutputParser()
        )

    async def generate_suggestion(
        self, latest_text: str, language: str, conversation_context: str = ""
    ) -> dict:
        """
        根据面试官最新发言 + 对话上下文 + 个人资料，生成回答提示。

        Args:
            latest_text: 面试官最新说的话
            language: 面试语言代码 ("en", "de")
            conversation_context: 格式化的对话上下文窗口

        Returns:
            {"suggestion": str, "sources": list[str]}
        """
        interview_language = LANG_MAP.get(language, "English")

        # 先检索相关文档（用于返回 sources）
        docs = self.retriever.invoke(latest_text)
        sources = list({doc.metadata.get("source", "unknown") for doc in docs})

        # 生成回答提示
        suggestion = await self.chain.ainvoke({
            "latest_text": latest_text,
            "conversation": conversation_context,
            "interview_language": interview_language,
        })

        return {
            "suggestion": suggestion.strip(),
            "sources": sources,
        }

    def generate_suggestion_sync(
        self, latest_text: str, language: str, conversation_context: str = ""
    ) -> dict:
        """同步版本（用于测试）"""
        interview_language = LANG_MAP.get(language, "English")

        docs = self.retriever.invoke(latest_text)
        sources = list({doc.metadata.get("source", "unknown") for doc in docs})

        suggestion = self.chain.invoke({
            "latest_text": latest_text,
            "conversation": conversation_context,
            "interview_language": interview_language,
        })

        return {
            "suggestion": suggestion.strip(),
            "sources": sources,
        }
