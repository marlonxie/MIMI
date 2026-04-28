"""全局 LLM 状态管理：active provider + 各 provider 的 api key 缓存。

启动时从环境变量（.env 路径）读所有已知 provider 的 key 到 self._keys。
运行时 set_key() 覆盖（前端 Settings 推送场景）。

Translator / IntentClassifier / RAGEngine 持有 manager 引用，
每次 _try_build() 调 manager.has_key() / make_llm() 决定能否构建 chain。
"""

import os

from llm.providers import PROVIDER_MAP, create_llm, needs_api_key


class LLMManager:
    """LLM provider + api key 单例状态。"""

    def __init__(self, default_provider: str = "gemini"):
        self.active_provider = default_provider
        self._keys: dict[str, str] = {}
        # 启动时从 env 读所有已知 provider 的 key（兼容 .env 开发者路径）
        for provider, info in PROVIDER_MAP.items():
            env_var = info["env"]
            if env_var and os.environ.get(env_var):
                self._keys[provider] = os.environ[env_var]

    def has_key(self, provider: str | None = None) -> bool:
        """判断给定 provider（默认当前 active）是否就绪可建 chain。"""
        provider = provider or self.active_provider
        if not needs_api_key(provider):
            return True   # local 模型不需要 key
        return provider in self._keys

    def set_key(self, provider: str, api_key: str) -> None:
        """前端推送时调。同时切换 active_provider。"""
        self._keys[provider] = api_key
        self.active_provider = provider

    def make_llm(self, **kwargs):
        """按当前 active_provider 创建 LangChain Chat 模型实例。

        调用方应先用 has_key() 判断；缺 key 时这里会抛 RuntimeError。
        """
        if not self.has_key():
            raise RuntimeError(f"{self.active_provider} 缺 api key")
        return create_llm(
            self.active_provider,
            api_key=self._keys.get(self.active_provider),
            **kwargs,
        )
