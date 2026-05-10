"""rag/resources.py 单元测试 — 零依赖（无需 server / LLM / Whisper）。

所有测试用 tmp_path 隔离，不会动 ~/Library/Application Support/MIMI 真实数据。
"""

import sys
from pathlib import Path

# 让 from rag.resources 可解析（pytest 直接跑 / `python tests/unit/test_resources.py` 都能跑）
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag.resources import list_resources, delete_resource, clear_resources


def _make_file(path: Path, content: bytes = b"x") -> None:
    path.write_bytes(content)


# ---------- list_resources ----------

def test_list_empty_dir(tmp_path):
    """空目录返回空列表。"""
    assert list_resources(tmp_path) == []


def test_list_missing_dir(tmp_path):
    """目录不存在返回空列表（不抛异常）。"""
    missing = tmp_path / "nope"
    assert list_resources(missing) == []


def test_list_filters_unsupported(tmp_path):
    """只返回 .pdf / .md / .txt；.py / .docx / .json 全部过滤掉。"""
    _make_file(tmp_path / "a.pdf")
    _make_file(tmp_path / "b.md")
    _make_file(tmp_path / "c.txt")
    _make_file(tmp_path / "d.py")
    _make_file(tmp_path / "e.docx")
    _make_file(tmp_path / "f.json")
    files = list_resources(tmp_path)
    names = {f["name"] for f in files}
    assert names == {"a.pdf", "b.md", "c.txt"}


def test_list_returns_size_mtime(tmp_path):
    """返回的 dict 含正确的 name / size / mtime。"""
    payload = b"hello world" * 10
    f = tmp_path / "resume.pdf"
    _make_file(f, payload)
    files = list_resources(tmp_path)
    assert len(files) == 1
    entry = files[0]
    assert entry["name"] == "resume.pdf"
    assert entry["size"] == len(payload)
    assert entry["mtime"] == f.stat().st_mtime


# ---------- delete_resource ----------

def test_delete_existing(tmp_path):
    """删除存在的支持类型文件 → 文件消失。"""
    f = tmp_path / "a.pdf"
    _make_file(f)
    ok, reason = delete_resource(tmp_path, "a.pdf")
    assert ok is True
    assert reason == ""
    assert not f.exists()


def test_delete_path_traversal(tmp_path):
    """安全测试：name 含 '..' 不能跳出 rsrc_dir。"""
    parent = tmp_path.parent
    sentinel = parent / "should_not_be_deleted.txt"
    _make_file(sentinel)
    try:
        ok, reason = delete_resource(tmp_path, "../should_not_be_deleted.txt")
        assert ok is False
        assert "traversal" in reason
        assert sentinel.exists()
    finally:
        if sentinel.exists():
            sentinel.unlink()


def test_delete_absolute_path_rejected(tmp_path):
    """安全测试：name 是绝对路径也应拒绝。"""
    other = tmp_path.parent / "other.txt"
    _make_file(other)
    try:
        ok, reason = delete_resource(tmp_path, str(other))
        assert ok is False
        assert "traversal" in reason
        assert other.exists()
    finally:
        if other.exists():
            other.unlink()


def test_delete_nonexistent(tmp_path):
    """删不存在的文件 → False，不抛异常。"""
    ok, reason = delete_resource(tmp_path, "ghost.pdf")
    assert ok is False
    assert "not found" in reason


def test_delete_unsupported_extension(tmp_path):
    """删不支持类型的文件 → False（即使文件存在）。"""
    f = tmp_path / "bad.exe"
    _make_file(f)
    ok, reason = delete_resource(tmp_path, "bad.exe")
    assert ok is False
    assert "unsupported" in reason
    assert f.exists()


def test_delete_unicode_nfd_nfc_fallback(tmp_path):
    """macOS APFS 文件名 NFC/NFD 不一致时，delete 应能 fallback 找到正确的形式。"""
    import unicodedata
    # "résumé.pdf"：NFC 是 "r\u00e9sum\u00e9.pdf"；NFD 是 "re\u0301sume\u0301.pdf"
    nfc_name = "résumé.pdf"
    nfd_name = unicodedata.normalize("NFD", nfc_name)
    # 文件名以 NFD 形式存到磁盘（模拟 APFS）
    (tmp_path / nfd_name).write_bytes(b"x")
    # 用 NFC 形式来删 — 应该 fallback 找到 NFD 版本
    ok, reason = delete_resource(tmp_path, nfc_name)
    assert ok is True, f"NFD fallback failed: {reason}"


# ---------- clear_resources ----------

def test_clear_removes_files_and_chroma(tmp_path):
    """清空：rsrc_dir 下支持类型文件全删 + chroma_dir 整个 rmtree。"""
    rsrc_dir = tmp_path / "resources"
    chroma_dir = tmp_path / "chroma_store"
    rsrc_dir.mkdir()
    chroma_dir.mkdir()

    _make_file(rsrc_dir / "a.pdf")
    _make_file(rsrc_dir / "b.md")
    _make_file(chroma_dir / "chroma.sqlite3")
    (chroma_dir / "subdir").mkdir()
    _make_file(chroma_dir / "subdir" / "blob")

    clear_resources(rsrc_dir, chroma_dir)

    assert list(rsrc_dir.iterdir()) == []
    assert not chroma_dir.exists()


def test_clear_preserves_unsupported_files(tmp_path):
    """clear 只删支持类型；用户其他文件（README 等）保留。"""
    rsrc_dir = tmp_path / "resources"
    chroma_dir = tmp_path / "chroma_store"
    rsrc_dir.mkdir()
    chroma_dir.mkdir()

    _make_file(rsrc_dir / "resume.pdf")
    _make_file(rsrc_dir / ".DS_Store")  # macOS 系统文件
    _make_file(rsrc_dir / "notes.docx")  # 用户其他文件

    clear_resources(rsrc_dir, chroma_dir)

    remaining = {p.name for p in rsrc_dir.iterdir()}
    assert "resume.pdf" not in remaining
    assert ".DS_Store" in remaining
    assert "notes.docx" in remaining


def test_clear_missing_dirs(tmp_path):
    """两个目录都不存在时不抛异常。"""
    rsrc_dir = tmp_path / "absent_resources"
    chroma_dir = tmp_path / "absent_chroma"
    clear_resources(rsrc_dir, chroma_dir)  # 不应抛


# ---------- runner ----------

if __name__ == "__main__":
    # 不依赖 pytest，自己模拟 tmp_path
    import tempfile
    import traceback

    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for fn in tests:
        with tempfile.TemporaryDirectory() as d:
            try:
                fn(Path(d))
                print(f"  ✓ {fn.__name__}")
                passed += 1
            except Exception:
                print(f"  ✗ {fn.__name__}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
