"""集中配置：双通道（项目默认 + 测试）+ 通用 OpenAI 兼容接入。

通道：
- deepseek（项目默认）：DeepSeek 官方
- glm（仅测试）：日日新 Token Plan 的 glm-5.2

选择通道：环境变量 LLM_CHANNEL=deepseek|glm，或 CLI --channel。
密钥：LLM_API_KEY 优先，否则按通道取 DEEPSEEK_API_KEY / SENSENOVA_API_KEY。
源码不含任何密钥，只从环境变量读取。
"""
import os
from dataclasses import dataclass

CHANNELS = {
    "deepseek": {
        "label": "DeepSeek 官方（项目默认）",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "key_env": ("DEEPSEEK_API_KEY",),
        "env_prefix": "DEEPSEEK",
    },
    "glm": {
        "label": "日日新 Token Plan · glm-5.2（仅测试）",
        "base_url": "https://token.sensenova.cn/v1",
        "model": "glm-5.2",
        "key_env": ("SENSENOVA_API_KEY",),
        "env_prefix": "GLM",
    },
}

DEFAULT_CHANNEL = "deepseek"


def _first_env(*names: str, default: str = "") -> str:
    """按顺序取第一个非空环境变量。"""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def active_channel() -> str:
    name = (os.getenv("LLM_CHANNEL") or DEFAULT_CHANNEL).strip()
    return name if name in CHANNELS else DEFAULT_CHANNEL


def list_channels() -> list[tuple[str, str, str, str]]:
    """返回 (name, label, base_url, model) 列表，供 CLI 展示。"""
    return [(n, c["label"], c["base_url"], c["model"]) for n, c in CHANNELS.items()]


@dataclass(frozen=True)
class Settings:
    channel: str = DEFAULT_CHANNEL
    # 检索
    top_k: int = 4
    min_score: float = 0.3      # 检索置信度阈值：低于此值按“未命中”转人工（阈值随检索模式不同）
    retrieval: str = "bm25"     # bm25 | hybrid；默认 bm25——实测 hybrid 在本语料 R@1 无增益
    rrf_k: int = 60
    query_expansion: str = "auto"  # off | auto | llm：auto=有 Key 时启用 LLM 查询扩展
    profile: str = "finance"       # finance | generic（领域提示词与合规护栏）
    # 输入
    max_input_chars: int = 500
    # LLM：超时与重试必须显式，禁止依赖默认值
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 3
    llm_backoff_base_s: float = 1.0
    llm_backoff_max_s: float = 10.0
    wall_clock_budget_s: float = 60.0
    # 模型与端点（由通道决定，可被 <PREFIX>_BASE_URL / <PREFIX>_MODEL 覆盖）
    model: str = CHANNELS[DEFAULT_CHANNEL]["model"]
    api_base: str = CHANNELS[DEFAULT_CHANNEL]["base_url"]


def settings_for(name: str | None = None) -> Settings:
    """按通道取配置（不传则取当前通道）。

    用途：L3 异构裁判需要「被测通道」与「裁判通道」不一样，
    因此这里必须支持显式指定通道，而不是依赖全局 LLM_CHANNEL。
    """
    name = name if name in CHANNELS else active_channel()
    ch = CHANNELS[name]
    prefix = ch["env_prefix"]
    retrieval = (_first_env("RETRIEVAL", default="bm25") or "bm25").strip().lower()
    if retrieval not in ("bm25", "hybrid"):
        retrieval = "bm25"
    expansion = (_first_env("QUERY_EXPANSION", default="auto") or "auto").strip().lower()
    if expansion not in ("off", "auto", "llm"):
        expansion = "auto"
    # 两种检索器的分数尺度不同：BM25 是 0~20+ 的原始分，hybrid 归一化到 0~1。
    # 因此阈值必须分模式给默认值，否则换检索器会把所有问题打成“转人工”。
    default_min = "0.30" if retrieval == "hybrid" else "0.5"
    return Settings(
        channel=name,
        top_k=int(_first_env("TOP_K", default="4")),
        min_score=float(_first_env("MIN_SCORE", default=default_min)),
        retrieval=retrieval,
        rrf_k=int(_first_env("RRF_K", default="60")),
        query_expansion=expansion,
        profile=(_first_env("APP_PROFILE", default="finance") or "finance").strip().lower(),
        max_input_chars=int(_first_env("MAX_INPUT_CHARS", default="500")),
        llm_timeout_s=float(_first_env("LLM_TIMEOUT_S", default="30")),
        llm_max_retries=int(_first_env("LLM_MAX_RETRIES", default="3")),
        wall_clock_budget_s=float(_first_env("WALL_CLOCK_BUDGET_S", default="60")),
        model=_first_env(f"{prefix}_MODEL", default=ch["model"]),
        api_base=_first_env(f"{prefix}_BASE_URL", default=ch["base_url"]),
    )


def load_settings() -> Settings:
    return settings_for(active_channel())


def api_key_for(name: str | None = None) -> str:
    """按通道取密钥：LLM_API_KEY 通用兜底，否则取该通道专属变量。"""
    ch = CHANNELS[name if name in CHANNELS else active_channel()]
    return _first_env("LLM_API_KEY", *ch["key_env"], default="")


def api_key() -> str:
    return api_key_for(active_channel())
