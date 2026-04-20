"""SharedHistory.get_focused_context 的边界测试。零依赖。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from conversation.history import SharedHistory


def _setup_history():
    """准备一个含 7 句的 history，模拟 interviewer + me 交替。"""
    h = SharedHistory(context_window_size=10, export_path="/tmp/mimi-test-tr")
    h.add_sentence("interviewer", "Hello there.", "en", sentence_id="s1")
    h.add_sentence("me", "Hi, nice to meet you.", "en", sentence_id="s2")
    h.add_sentence("interviewer", "Tell me about your K8s experience.", "en", sentence_id="s3")
    h.add_sentence("me", "Sure, I've been working with it for 3 years.", "en", sentence_id="s4")
    h.add_sentence("interviewer", "What was the largest cluster?", "en", sentence_id="s5")
    h.add_sentence("me", "About 200 nodes.", "en", sentence_id="s6")
    h.add_sentence("interviewer", "How did you handle scaling?", "en", sentence_id="s7")
    return h


def test_found_in_middle():
    h = _setup_history()
    query, ctx = h.get_focused_context("s5")
    assert query == "What was the largest cluster?"
    # 前 5 句（s1..s4 只有 4 句可用，因为 s5 前只有 4 句）
    lines = ctx.split("\n")
    assert len(lines) == 4
    assert lines[0].startswith("[Interviewer] Hello there.")
    assert lines[-1].startswith("[Me] Sure, I've been working")


def test_found_last():
    h = _setup_history()
    query, ctx = h.get_focused_context("s7")
    assert query == "How did you handle scaling?"
    # 取前 5 句（s2..s6）
    lines = ctx.split("\n")
    assert len(lines) == 5
    assert lines[0].startswith("[Me] Hi, nice to meet you.")
    assert lines[-1].startswith("[Me] About 200 nodes.")


def test_found_first():
    h = _setup_history()
    query, ctx = h.get_focused_context("s1")
    assert query == "Hello there."
    assert ctx == ""  # 之前没句子


def test_not_found():
    h = _setup_history()
    query, ctx = h.get_focused_context("nonexistent-id")
    assert query == ""
    assert ctx == ""


def test_entry_without_id_skipped():
    """没 id 的 entry 不能被 get_focused_context 找到。"""
    h = SharedHistory(context_window_size=10, export_path="/tmp/mimi-test-tr")
    h.add_sentence("interviewer", "No id entry.", "en")  # 不传 sentence_id
    query, ctx = h.get_focused_context("anything")
    assert query == ""
    assert ctx == ""


def test_single_history_item():
    """history 只有 1 句时，找到后 context 为空。"""
    h = SharedHistory(context_window_size=10, export_path="/tmp/mimi-test-tr")
    h.add_sentence("interviewer", "Only one.", "en", sentence_id="lone")
    query, ctx = h.get_focused_context("lone")
    assert query == "Only one."
    assert ctx == ""


def test_add_sentence_persists_id():
    """add_sentence 把 sentence_id 写到 entry 里。"""
    h = SharedHistory(context_window_size=10, export_path="/tmp/mimi-test-tr")
    entry = h.add_sentence("me", "hello", "en", sentence_id="xyz")
    assert entry["id"] == "xyz"
    assert h.history[-1]["id"] == "xyz"


def test_add_sentence_without_id_has_no_id_key():
    """不传 sentence_id，entry 不含 id key（保持向后兼容）。"""
    h = SharedHistory(context_window_size=10, export_path="/tmp/mimi-test-tr")
    entry = h.add_sentence("me", "hello", "en")
    assert "id" not in entry


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"✓ {name}")
            except AssertionError as e:
                print(f"✗ {name}: {e}")
                raise
    print("\n所有 history.get_focused_context 测试通过")
