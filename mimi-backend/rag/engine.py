"""RAG 引擎 — 检索个人资料 + 生成回答提示"""

import yaml
from pathlib import Path
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

from translation.langchain_translator import _create_llm

load_dotenv(Path(__file__).parent.parent / ".env")

LANG_MAP = {"en": "English", "de": "German"}
NATIVE_LANG_MAP = {"zh": "中文", "en": "English"}

RAG_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是实时面试答案助手。候选人母语是 {native_language_name}，面试语言是 {interview_language_name}。

**输出格式（严格三段，全部显示，不要省略）**：

📌 **问题理解**（用 {native_language_name}，一句话 ≤20 字）
<直击面试官在问什么维度，去掉客套和语气词>

💡 **要点**（3-5 条双语对照，每条 ≤15 字）
• <{native_language_name} 要点> → <{interview_language_name} keyword>
• ...

🗣️ **示例回答**（用 {interview_language_name}，2-3 句 ≤60 词）
<STAR 风格：情景→动作→具体数字→结果。必含真实数字/技术术语。>

**风格硬约束**：
- 禁用：maybe, I think, kind of, sort of, um, uh
- 示例回答用 past tense 讲经历
- 每个要点是名词短语，不是完整句子
- 如果资料不相关，基于通用面试常识，要点减为 2-3 条

**候选人资料**（按相关度排序）:
{context}

**最近对话**:
{conversation}"""),
    ("human", "面试官刚才说的：\n{latest_text}"),
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

        # LLM chain（不含 retriever，retriever 单独调用避免重复检索）
        self.answer_chain = RAG_PROMPT | self.llm | StrOutputParser()

    def _retrieve_and_format(self, query: str) -> tuple[str, list[str]]:
        """检索相关文档，返回 (格式化文本, 来源列表)"""
        docs = self.retriever.invoke(query)
        context = _format_docs(docs)
        sources = list({doc.metadata.get("source", "unknown") for doc in docs})
        return context, sources

    async def generate_suggestion(
        self,
        latest_text: str,
        interview_language: str,
        native_language: str,
        conversation_context: str = "",
    ) -> dict:
        """根据面试官最新发言 + 对话上下文 + 个人资料，生成三段式双语回答提示。

        Args:
            latest_text: 面试官最新说的话（或连续独白）
            interview_language: 面试语言 ISO 代码（"en", "de"）
            native_language: 用户母语 ISO 代码（"zh", "en"）
            conversation_context: 格式化的对话上下文窗口

        Returns:
            {"suggestion": str, "sources": list[str]}
        """
        context, sources = self._retrieve_and_format(latest_text)

        suggestion = await self.answer_chain.ainvoke({
            "context": context,
            "latest_text": latest_text,
            "conversation": conversation_context,
            "interview_language_name": LANG_MAP.get(interview_language, "English"),
            "native_language_name": NATIVE_LANG_MAP.get(native_language, "中文"),
        })

        return {
            "suggestion": suggestion.strip(),
            "sources": sources,
        }

    def generate_suggestion_sync(
        self,
        latest_text: str,
        interview_language: str,
        native_language: str,
        conversation_context: str = "",
    ) -> dict:
        """同步版本（用于测试）"""
        context, sources = self._retrieve_and_format(latest_text)

        suggestion = self.answer_chain.invoke({
            "context": context,
            "latest_text": latest_text,
            "conversation": conversation_context,
            "interview_language_name": LANG_MAP.get(interview_language, "English"),
            "native_language_name": NATIVE_LANG_MAP.get(native_language, "中文"),
        })

        return {
            "suggestion": suggestion.strip(),
            "sources": sources,
        }
