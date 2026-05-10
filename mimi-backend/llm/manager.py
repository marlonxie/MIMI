"""全局 LLM 状态管理：active provider + 各 provider 的 api key 缓存。

启动时从环境变量（.env 路径）读所有已知 provider 的 key 到 self._keys。
运行时 set_key() 覆盖（前端 Settings 推送场景）。

Translator / IntentClassifier / RAGEngine 持有 manager 引用，
每次 _try_build() 调 manager.has_key() / make_llm() 决定能否构建 chain。
"""

import os

from llm.providers import PROVIDER_MAP, create_llm, needs_api_key

# preferred provider 缺 key 时降级到的 local provider
FALLBACK_LOCAL_PROVIDER = "ollama"


class LLMManager:
    """LLM provider + api key 单例状态。"""

    def __init__(self, default_provider: str = "gemini", default_model: str | None = None):
        """构造时可指定 model 覆盖 PROVIDER_MAP 默认 (用于 bench 比较同 provider 不同 model)."""
        self._model_override = default_model
        self._keys: dict[str, str] = {}
        # 启动时从 env 读所有已知 provider 的 key（兼容 .env 开发者路径）
        for provider, info in PROVIDER_MAP.items():
            env_var = info["env"]
            if env_var and os.environ.get(env_var):
                self._keys[provider] = os.environ[env_var]

        # 智能 fallback：preferred provider 需 key 但缺 key 时降级到本地 ollama
        # 用户配了 key 走 cloud；零配置开箱用本地（daemon 起着即可）
        if needs_api_key(default_provider) and default_provider not in self._keys:
            print(f"[llm] {default_provider} 缺 key，fallback → {FALLBACK_LOCAL_PROVIDER}")
            self.active_provider = FALLBACK_LOCAL_PROVIDER
        else:
            self.active_provider = default_provider

    def has_key(self, provider: str | None = None) -> bool:
        """判断给定 provider（默认当前 active）是否就绪可建 chain。"""
        provider = provider or self.active_provider
        if not needs_api_key(provider):
            return True   # local 模型不需要 key
        return provider in self._keys

    def set_key(self, provider: str, api_key: str) -> None:
        """前端推送时调。同时切换 active_provider。

        api_key 非空才覆盖 _keys[provider]；空 key 表示"只切 active，沿用之前已加载的
        key"（来源 .env 启动时加载、之前 set 过、或本地 provider 根本不需要 key）。
        否则用户切到 ollama 再切回 gemini 时会用空字符串覆盖掉 .env 加载的真 key。
        """
        if api_key:
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
            model=self._model_override,
            **kwargs,
        )
