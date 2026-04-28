"""统一 LLM 创建 + key 管理。

Translator / IntentClassifier / RAGEngine 都从这里取 LLM 实例：
- llm/providers.py: PROVIDER_MAP + create_llm 工厂（用 LangChain init_chat_model）
- llm/manager.py:   LLMManager 单例，缓存 active provider + 各 provider 的 api key

API key 来源优先级（启动时由 LLMManager 自动读取）：
1. .env / 系统环境变量 GOOGLE_API_KEY / ANTHROPIC_API_KEY（开发者路径）
2. WebSocket 推送 set_api_keys（前端 Settings 路径，运行时覆盖）
"""

from llm.providers import PROVIDER_MAP, create_llm, default_model_for, needs_api_key
from llm.manager import LLMManager

__all__ = ["PROVIDER_MAP", "create_llm", "default_model_for", "needs_api_key", "LLMManager"]
