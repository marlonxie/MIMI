"""参考资料目录的纯函数操作 — list / delete / clear。

抽出来独立成模块是为了可单元测试（不依赖 server.py / WebSocket / 全局 rag_engine）。
所有路径都接收为参数，调用方负责 expanduser。
"""

import shutil
from pathlib import Path

# 与 rag/indexer.py LOADER_MAP 对齐
SUPPORTED_EXTS = {".pdf", ".md", ".txt"}


def list_resources(rsrc_dir: Path) -> list[dict]:
    """扫描 resources 目录，返回所有支持类型的文件元数据。

    Args:
        rsrc_dir: 资料目录（已 expanduser 的绝对路径）

    Returns:
        [{"name": "resume.pdf", "size": 12345, "mtime": 1700000000.0}, ...]
        目录不存在时返回 []
    """
    if not rsrc_dir.exists():
        return []

    files = []
    for p in sorted(rsrc_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            stat = p.stat()
            files.append({
                "name": p.name,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })
    return files


def delete_resource(rsrc_dir: Path, name: str) -> tuple[bool, str]:
    """删除 rsrc_dir 下名为 name 的文件。

    Args:
        rsrc_dir: 资料目录
        name: 文件名（仅文件名，不能包含路径分隔符 / .. 等）

    Returns:
        (True, "") 删除成功；(False, reason) 失败带具体原因。

    Path traversal 防御：name 必须解析后仍在 rsrc_dir 内（拒绝 "../etc/passwd"）。
    """
    rsrc_root = rsrc_dir.resolve()
    target = (rsrc_root / name).resolve()

    if not target.is_relative_to(rsrc_root):
        return False, f"path traversal: {name!r} outside {rsrc_root}"
    if not target.exists():
        # macOS APFS 上文件名可能用 NFD 存储，前端 NFC 名字会 mismatch；
        # 这里 fallback 用 Unicode normalization 再找一次
        import unicodedata
        for form in ("NFC", "NFD"):
            alt = (rsrc_root / unicodedata.normalize(form, name)).resolve()
            if alt.is_relative_to(rsrc_root) and alt.is_file():
                target = alt
                break
        else:
            return False, f"file not found: {target}"
    if not target.is_file():
        return False, f"not a regular file: {target}"
    if target.suffix.lower() not in SUPPORTED_EXTS:
        return False, f"unsupported extension: {target.suffix}"

    target.unlink()
    return True, ""


def clear_resources(rsrc_dir: Path, chroma_dir: Path) -> None:
    """一键清除：删 rsrc_dir 下所有支持类型的文件 + 整个 chroma_dir。

    chroma_dir 用 rmtree 整个删；rsrc_dir 只删支持类型，保留用户可能放进去的其他东西。
    """
    if rsrc_dir.exists():
        for p in rsrc_dir.iterdir():
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                p.unlink()
    if chroma_dir.exists():
        shutil.rmtree(chroma_dir)
