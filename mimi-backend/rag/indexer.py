"""文档索引工具 — 加载、切片、embedding、存入 ChromaDB"""

import shutil
import yaml
from pathlib import Path
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, TextLoader

load_dotenv(Path(__file__).parent.parent / ".env")

# 文件类型 → Loader 映射
LOADER_MAP = {
    ".pdf": PyPDFLoader,
    ".txt": TextLoader,
    ".md": TextLoader,
}


class RAGIndexer:
    """离线文档索引工具"""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        rag_config = config["rag"]
        # expanduser 让 "~/Library/Application Support/MIMI/..." 解析成绝对路径
        # （旧 config 用的相对路径 ../resources 没 ~ 也照常工作，expanduser 是 no-op）
        self.resources_path = Path(rag_config["resources_path"]).expanduser()
        self.chroma_path = str(Path(rag_config["chroma_path"]).expanduser())
        self.chunk_size = rag_config.get("chunk_size", 500)
        self.chunk_overlap = rag_config.get("chunk_overlap", 50)

        self.embeddings = HuggingFaceEmbeddings(
            model_name=rag_config["embedding_model"],
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

    def load_documents(self) -> tuple[list, int]:
        """从 resources/ 加载所有支持的文档。

        Returns:
            (docs, files_count) — docs 是 LangChain Document 列表（一个文件可能切多页 doc）；
            files_count 是被识别成功的源文件数
        """
        docs = []
        files_count = 0
        if not self.resources_path.exists():
            print(f"资料目录不存在: {self.resources_path}")
            return docs, files_count

        for file_path in sorted(self.resources_path.rglob("*")):
            if file_path.suffix.lower() in LOADER_MAP:
                loader_cls = LOADER_MAP[file_path.suffix.lower()]
                try:
                    loader = loader_cls(str(file_path))
                    loaded = loader.load()
                    docs.extend(loaded)
                    files_count += 1
                    print(f"  加载: {file_path.name} ({len(loaded)} 页/段)")
                except Exception as e:
                    print(f"  跳过: {file_path.name} (错误: {e})")

        return docs, files_count

    def split_documents(self, docs: list) -> list:
        """文档切片"""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ".", " ", ""],
        )
        return splitter.split_documents(docs)

    def index(self) -> tuple[Chroma | None, int]:
        """完整索引流程：加载 → 切片 → embedding → 存入 ChromaDB。

        Returns:
            (vector_store, files_indexed) — files_indexed 是 resources/ 下被识别成功的源文件数；
            没找到文档时返回 (None, 0)
        """
        print("=" * 50)
        print("MIMI RAG 文档索引")
        print("=" * 50)

        # 清除旧索引（全量重建）
        chroma_dir = Path(self.chroma_path)
        if chroma_dir.exists():
            shutil.rmtree(chroma_dir)
            print(f"已清除旧索引: {chroma_dir}")

        # 加载文档
        print(f"\n从 {self.resources_path} 加载文档...")
        docs, files_count = self.load_documents()
        if not docs:
            print("没有找到文档！请将 PDF/MD/TXT 文件放入 resources/ 目录")
            return None, 0

        print(f"共加载 {files_count} 个文件，{len(docs)} 个文档段")

        # 切片
        print(f"\n切片中 (chunk_size={self.chunk_size}, overlap={self.chunk_overlap})...")
        chunks = self.split_documents(docs)
        print(f"共生成 {len(chunks)} 个文本块")

        # 索引
        print(f"\n生成 embedding 并存入 ChromaDB...")
        vector_store = Chroma.from_documents(
            documents=chunks,
            embedding=self.embeddings,
            collection_name="interview_materials",
            persist_directory=self.chroma_path,
        )
        print(f"索引完成！存储在 {self.chroma_path}")
        print(f"\n摘要:")
        print(f"  源文件数: {files_count}")
        print(f"  文档段数: {len(docs)}")
        print(f"  文本块数: {len(chunks)}")
        print(f"  向量维度: 384 (MiniLM)")

        return vector_store, files_count


if __name__ == "__main__":
    indexer = RAGIndexer()
    indexer.index()
