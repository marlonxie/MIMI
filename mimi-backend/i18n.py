"""语言代码 ↔ 各场景展示名（single source of truth）。

加新语种只改这一个文件。三个 callsite：
- translation/langchain_translator.py 用 zh_name（prompt 是中文）
- rag/engine.py 用 en_name（prompt 是中英混合）
- 任何地方需要"用户母语自称"用 native_name（UI 提示等）
"""

LANGUAGES: dict[str, dict[str, str]] = {
    "en": {"zh_name": "英语",     "en_name": "English",    "native_name": "English"},
    "de": {"zh_name": "德语",     "en_name": "German",     "native_name": "Deutsch"},
    "es": {"zh_name": "西班牙语", "en_name": "Spanish",    "native_name": "Español"},
    "fr": {"zh_name": "法语",     "en_name": "French",     "native_name": "Français"},
    "it": {"zh_name": "意大利语", "en_name": "Italian",    "native_name": "Italiano"},
    "pt": {"zh_name": "葡萄牙语", "en_name": "Portuguese", "native_name": "Português"},
    "nl": {"zh_name": "荷兰语",   "en_name": "Dutch",      "native_name": "Nederlands"},
    "ja": {"zh_name": "日语",     "en_name": "Japanese",   "native_name": "日本語"},
    "ko": {"zh_name": "韩语",     "en_name": "Korean",     "native_name": "한국어"},
    "zh": {"zh_name": "中文",     "en_name": "Mandarin",   "native_name": "中文"},
}

# 业务白名单：前端 picker 与未来后端校验共用同一来源
INTERVIEW_LANGS = ("en", "de", "es", "fr", "it", "pt", "nl", "ja", "ko", "zh")
NATIVE_LANGS = ("zh", "en", "de", "ja", "es")


def zh_name(code: str, fallback: str = "English") -> str:
    return LANGUAGES.get(code, {}).get("zh_name", fallback)


def en_name(code: str, fallback: str = "English") -> str:
    return LANGUAGES.get(code, {}).get("en_name", fallback)


def native_name(code: str, fallback: str = "中文") -> str:
    return LANGUAGES.get(code, {}).get("native_name", fallback)
