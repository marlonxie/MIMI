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
    # 占位（下轮实现）：本地 MLX 模型不走 init_chat_model，
    # 需自家 BaseChatModel 子类（用 mlx_lm.load + generate）
    # "local_mlx": {
    #     "lc": None,
    #     "env": None,
    #     "api_kwarg": None,
    #     "default_model": "mlx-community/Qwen2.5-7B-Instruct-4bit",
    #     "kind": "local",
    # },
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
    if info["kind"] == "local":
        raise NotImplementedError(f"{provider} (local) 尚未实现，下轮加")

    model = model or info["default_model"]
    if api_key:
        kwargs[info["api_kwarg"]] = api_key
    return init_chat_model(f"{info['lc']}:{model}", **kwargs)


def default_model_for(provider: str) -> str:
    return PROVIDER_MAP[provider]["default_model"]


def needs_api_key(provider: str) -> bool:
    """remote provider 需要 api key；local 不需要。"""
    return PROVIDER_MAP[provider]["kind"] == "remote"
