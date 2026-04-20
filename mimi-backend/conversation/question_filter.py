"""本地启发式过滤 — 三层触发架构的第一层。

O(1) 判断，零 LLM 调用。只过滤**明确垃圾**（短、纯标点、寒暄黑名单）。
**不负责判定是否为问题** —— 语义判断交给 intent_classifier.py。

设计原则：
- 保守，宁可放行也别误杀（intent LLM 会做更精细判定）
- 多语言黑名单按 interview_language 切换
"""

BLACKLISTS: dict[str, set[str]] = {
    "en": {
        "ok", "okay", "got it", "right", "i see", "thanks", "thank you",
        "sure", "yeah", "yep", "uh huh", "mhm", "no worries", "interesting",
        "cool", "nice", "gotcha", "exactly", "makes sense", "alright",
    },
    "de": {
        "ja", "okay", "stimmt", "ach so", "verstehe", "genau", "klar",
        "gut", "super", "cool", "danke", "alles klar",
    },
}


def is_likely_filler(text: str, language: str = "en") -> bool:
    """判断是否为寒暄/过渡/填充语（应丢弃）。

    Args:
        text: 原始句子
        language: ISO 639-1 面试语言代码

    Returns:
        True → 应该丢弃（不进 intent/RAG）
        False → 放行给下一层判定
    """
    t = text.strip().lower().rstrip(".,!?;:。，！？；：")
    if not t:
        return True
    if len(t.split()) < 3:
        return True
    blacklist = BLACKLISTS.get(language, BLACKLISTS["en"])
    if t in blacklist:
        return True
    return False
