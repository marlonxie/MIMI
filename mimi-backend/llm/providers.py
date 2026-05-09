"""LLM provider 注册表 + 统一创建工厂。

用 LangChain `init_chat_model` 替代手写 importlib 反射。
显式传 provider-specific 参数名（`google_api_key` / `anthropic_api_key`）—— 官方文档
推荐的方式，不依赖 LangChain 内部参数规范化逻辑。

加新 provider 只要在 PROVIDER_MAP 加一行；如是本地模型，需要实现 `BaseChatModel` 子类
并在 create_llm 的 local 分支里 dispatch。
"""

from langchain.chat_models import init_chat_model


PROVIDER_MAP: dict[str, dict] = {
    "gemini": {
        "lc": "google_genai",          # init_chat_model("google_genai:...")
        "env": "GOOGLE_API_KEY",        # 启动时 manager 从此 env var 读
        "api_kwarg": "google_api_key",  # 显式传给 init_chat_model 的参数名
        "default_model": "gemini-2.5-flash",
        "kind": "remote",
    },
    "claude": {
        "lc": "anthropic",
        "env": "ANTHROPIC_API_KEY",
        "api_kwarg": "anthropic_api_key",
        "default_model": "claude-sonnet-4-5-20250929",
        "kind": "remote",
    },
    "ollama": {
        "lc": "ollama",                 # init_chat_model(..., model_provider="ollama")
        "env": None,                    # 本地 daemon，无需 api key
        "api_kwarg": None,
        # bench 显示 4B-instruct-2507 在 IF + 延迟上同时优于 8B-hybrid（参考 scripts/bench_llm.py）
        "default_model": "qwen3:4b-instruct-2507-q4_K_M",
        "kind": "local",
    },
}


def create_llm(provider: str, api_key: str | None = None, model: str | None = None,
               **kwargs):
    """创建 LangChain Chat 模型实例。

    Args:
        provider: PROVIDER_MAP 的 key（"gemini" / "claude"）
        api_key: 显式 key；None 时让 LangChain 走 env var 默认（兼容 .env 路径）
        model:   model id；None 用 PROVIDER_MAP[provider]["default_model"]
        **kwargs: 透传给底层 ChatModel（例如 temperature=0）
    """
    if provider not in PROVIDER_MAP:
        raise ValueError(f"未知 provider: {provider}; 支持 {list(PROVIDER_MAP.keys())}")

    info = PROVIDER_MAP[provider]
    model = model or info["default_model"]
    if api_key and info["api_kwarg"]:
        kwargs[info["api_kwarg"]] = api_key
    # Qwen3 默认 thinking 模式会拖慢 TTFT 数倍；翻译/intent 是短输出确定性任务，关掉
    if info["lc"] == "ollama":
        kwargs.setdefault("reasoning", False)
    # 显式 model_provider，避免 model 名含冒号（如 "qwen3:8b"）被 init_chat_model 误拆
    return init_chat_model(model, model_provider=info["lc"], **kwargs)


def default_model_for(provider: str) -> str:
    return PROVIDER_MAP[provider]["default_model"]


def needs_api_key(provider: str) -> bool:
    """remote provider 需要 api key；local 不需要。"""
    return PROVIDER_MAP[provider]["kind"] == "remote"
