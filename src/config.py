"""集中配置：一个 OpenAI 兼容端点 + 检索/生成/降级参数。

端点、模型、密钥全部来自环境变量，源码不含任何密钥，也不绑定某一家服务商：

- `LLM_API_KEY`（也可用 `DEEPSEEK_API_KEY`）
- `LLM_BASE_URL`（默认 `https://api.deepseek.com/v1`）
- `LLM_MODEL`（默认 `deepseek-chat`）

换服务商只改这两个变量，不改代码；未配置 Key 时生成层自动降级为抽取式回答。
"""
import os
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


def _first_env(*names: str, default: str = "") -> str:
    """按顺序取第一个非空环境变量。"""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def endpoint_label(base_url: str) -> str:
    """从端点地址推出一个短标识，用于 trace 与页面展示。"""
    host = (urlparse(base_url).hostname or "").strip(".")
    if not host:
        return "custom"
    parts = host.split(".")
    if parts[0] in ("api", "www") and len(parts) > 2:
        parts = parts[1:]
    return parts[0] or "custom"


@dataclass(frozen=True)
class Settings:
    channel: str = "deepseek"      # 端点标识（展示用，不参与分支）
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
    # 模型与端点（可被 LLM_BASE_URL / LLM_MODEL 覆盖）
    model: str = DEFAULT_MODEL
    api_base: str = DEFAULT_BASE_URL


def load_settings() -> Settings:
    retrieval = (_first_env("RETRIEVAL", default="bm25") or "bm25").strip().lower()
    if retrieval not in ("bm25", "hybrid"):
        retrieval = "bm25"
    expansion = (_first_env("QUERY_EXPANSION", default="auto") or "auto").strip().lower()
    if expansion not in ("off", "auto", "llm"):
        expansion = "auto"
    base = (_first_env("LLM_BASE_URL", default=DEFAULT_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")
    # 两种检索器的分数尺度不同：BM25 是 0~20+ 的原始分，hybrid 归一化到 0~1。
    # 因此阈值必须分模式给默认值，否则换检索器会把所有问题打成“转人工”。
    default_min = "0.30" if retrieval == "hybrid" else "0.5"
    return Settings(
        channel=endpoint_label(base),
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
        model=_first_env("LLM_MODEL", default=DEFAULT_MODEL) or DEFAULT_MODEL,
        api_base=base,
    )


def api_key() -> str:
    """密钥：LLM_API_KEY 优先，兼容 DEEPSEEK_API_KEY。"""
    return _first_env("LLM_API_KEY", "DEEPSEEK_API_KEY", default="")
