"""IntentClassifier.should_respond 方向性断言。需要 GOOGLE_API_KEY。

LLM 输出非 100% 稳定，只断"明显正例 → yes"和"明显负例 → no"。
边缘模糊样本不在此覆盖（留给 diagnostic）。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")
from conversation.intent_classifier import IntentClassifier
from llm import LLMManager


CLEAR_YES_EN = [
    "Tell me about your Kubernetes experience",
    "How did you handle the fraud detection challenge?",
    "Can you walk me through your system design?",
    "What's the most difficult bug you've debugged?",
]

CLEAR_NO_EN = [
    "Got it",
    "Makes sense",
    "OK thanks for that",
    "So our team uses Python mostly",
    "Interesting, let me think",
]


def _load_classifier() -> IntentClassifier:
    return IntentClassifier(LLMManager())


async def _run():
    ic = _load_classifier()
    failures = []

    for text in CLEAR_YES_EN:
        yes = await ic.should_respond(text, context="", language="en")
        if not yes:
            failures.append(f"expected yes, got no: {text!r}")
        else:
            print(f"✓ yes: {text!r}")

    for text in CLEAR_NO_EN:
        yes = await ic.should_respond(text, context="", language="en")
        if yes:
            failures.append(f"expected no, got yes: {text!r}")
        else:
            print(f"✓ no : {text!r}")

    return failures


def test_intent_directional_english():
    failures = asyncio.run(_run())
    assert not failures, "Intent classifier 失误:\n  " + "\n  ".join(failures)


if __name__ == "__main__":
    test_intent_directional_english()
    print("\n所有 intent_classifier 方向性断言通过")
