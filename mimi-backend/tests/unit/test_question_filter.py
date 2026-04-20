"""question_filter.is_likely_filler 的启发式断言。零依赖。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from conversation.question_filter import is_likely_filler


def test_english_fillers_dropped():
    for t in ["OK", "okay.", "Got it.", "Right", "I see", "Thanks",
              "Thank you", "Sure", "Yeah", "Makes sense", "Interesting",
              "Gotcha", "Alright"]:
        assert is_likely_filler(t), f"should drop: {t!r}"


def test_english_questions_pass():
    for t in [
        "Tell me about Kubernetes",
        "What's your biggest weakness?",
        "How did you handle the fraud detection?",
        "Can you walk me through your approach?",
        "Why did you choose Python for this?",
    ]:
        assert not is_likely_filler(t), f"should pass: {t!r}"


def test_empty_and_punctuation_dropped():
    for t in ["", "   ", "...", "???", ".", ",!?"]:
        assert is_likely_filler(t), f"should drop: {t!r}"


def test_short_utterance_dropped():
    # < 3 词，即便不是寒暄也丢弃
    assert is_likely_filler("Two words")
    assert is_likely_filler("Huh?")
    # = 3 词刚好过关
    assert not is_likely_filler("What is Redux?")


def test_german_fillers():
    for t in ["Ja", "okay", "Stimmt", "Ach so", "Verstehe", "Genau",
              "Klar", "Alles klar", "Danke"]:
        assert is_likely_filler(t, language="de"), f"should drop (de): {t!r}"


def test_german_questions_pass():
    assert not is_likely_filler("Erzähl mir von deinem Projekt", language="de")
    assert not is_likely_filler("Warum hast du Python gewählt?", language="de")


def test_case_insensitivity():
    assert is_likely_filler("OK")
    assert is_likely_filler("ok")
    assert is_likely_filler("Ok")
    assert is_likely_filler("OKAY")


def test_trailing_punct_stripped():
    assert is_likely_filler("Got it.")
    assert is_likely_filler("Got it!")
    assert is_likely_filler("Got it?")
    assert is_likely_filler("Right,")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"✓ {name}")
            except AssertionError as e:
                print(f"✗ {name}: {e}")
                raise
    print("\n所有 question_filter 测试通过")
