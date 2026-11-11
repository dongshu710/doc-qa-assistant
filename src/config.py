"""集中配置：一个 OpenAI 兼容端点 + 检索/生成/降级参数。

端点、模型、密钥全部来自环境变量，源码不含任何密钥，也不绑定某一家服务商：

- `LLM_API_KEY`（也可用 `DEEPSEEK_API_KEY`）
- `LLM_BASE_URL`（默认 `https://api.deepseek.com/v1`）
- `LLM_MODEL`（默认 `deepseek-chat`）

换服务商只改这两个变量，不改代码；未配置 Key 时生成层自动降级为抽取式回答。
"""
import os
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from . import appconfig

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

_OVERRIDES: dict[str, str] = {}
_OVERRIDES_AT = 0.0
_OVERRIDES_KEY: tuple[int, str] | None = None


def _overrides() -> dict[str, str]:
    """界面配置加两层失效：写入版本号（精确）+ 1 秒 TTL（兜底）。

    只靠 TTL 会让「点了保存」后的同一次响应仍回显旧模型（实测复现），
    而设置面板恰好把「已保存的值」和「当前生效的值」并排显示——自相矛盾比慢一秒更糟。
    """
    global _OVERRIDES, _OVERRIDES_AT, _OVERRIDES_KEY
    now = time.monotonic()
    key = (appconfig.revision(), str(appconfig.path()))
    if key != _OVERRIDES_KEY or now - _OVERRIDES_AT > 1.0:
        _OVERRIDES = appconfig.as_env()
        _OVERRIDES_AT, _OVERRIDES_KEY = now, key
    return _OVERRIDES


def _first_env(*names: str, default: str = "") -> str:
    """按顺序取第一个非空值：界面配置优先，其次环境变量。

    界面里显式清空的项（空串）不再回落到环境变量——否则用户清不干净，会以为开关坏了。
    """
    overrides = _overrides()
    for name in names:
        if name in overrides:
            return overrides[name]
        value = os.getenv(name)
        if value:
            return value
    return default


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    """读整数型配置：坏值回落默认，不抛异常。

    为什么容错：`load_settings()` 在启动路径上，把 `KB_KEEP_VERSIONS` 手改成
    「三十」就会让整个服务起不来；而同一个值在设置面板那边（appconfig.keep_versions）
    是「回默认 30」。同一个配置两个入口两种行为，比坏值本身更难查。
    写的时候仍然严格（设置面板 update 里报错），这里只管读。
    """
    raw = (_first_env(name, default=str(default)) or "").strip()
    try:
        return max(minimum, int(raw))
    except (TypeError, ValueError):
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
    min_score: float = 0.3      # 检索置信度阈值：低于此值返回「无法找到答案」（阈值随检索模式不同）
    # 低于这个分数仍作答，但要加保留语气（「可能不是你要问的对象」）。
    # 为什么不是直接拒答：实测同一条语料里，正确回答的最低分与答非所问的最高分有重叠
    # （向量模式 0.69 vs 0.78），任何单一阈值都会错杀。重叠区间里唯一诚实的做法是
    # 把「像答案」降级成「最接近的段落」，把判断权交回给用户。
    hedge_score: float = 0.8
    retrieval: str = "vector"   # embedding | vector（零依赖基线）| bm25 | hybrid
    rrf_k: int = 60
    query_expansion: str = "auto"  # off | auto | llm：auto=有 Key 时启用 LLM 查询扩展
    profile: str = "finance"       # finance | generic（领域提示词与合规护栏）
    # embedding（OpenAI 兼容 /embeddings；bge 同协议）
    embedding_provider: str = "none"   # none | openai | bge
    embedding_base_url: str = ""
    embedding_model: str = ""
    embedding_api_key: str = ""
    embedding_dim: int = 0             # 0=构建时探测；配置后做一致性校验
    embedding_batch: int = 16
    embedding_timeout_s: float = 8.0
    embedding_max_retries: int = 2
    embedding_backoff_base_s: float = 0.5
    embedding_backoff_max_s: float = 4.0
    embedding_wall_clock_s: float = 30.0
    # 建库与单次查询是两种负载：建库要跑完全部批次，30 秒必然不够，
    # 分开配置才不会「一开 embedding 就超时、静默退回 n-gram」
    embedding_build_budget_s: float = 600.0
    embedding_index_dir: str = "data/index"
    embedding_recall_k: int = 48
    # 向量存储
    vector_store: str = "auto"         # auto | pure | numpy | faiss | faiss-ivf
    vector_ivf_nlist: int = 64
    vector_ivf_nprobe: int = 8
    # 输入
    max_input_chars: int = 500
    # 资料总长度上限：命中块拼起来超过这个数就按顺序裁掉后面的，并显式标注
    max_context_chars: int = 6000
    # 引用校验：strict 时「编号合法但内容不支持」的答案会降级为抽取式
    citation_strict: bool = False
    # 是否把异常原文回传前端：默认关，只在排查问题时打开
    debug: bool = False
    # 关键词直出：结构化条目命中后在本地输出，不调用任何 API
    keyword_mode: str = "on"            # on | off
    keyword_llm: str = "auto"           # auto=有 Key 才做整理 | off | on
    keyword_index: str = "data/index/keywords.json"
    keyword_top_n: int = 3
    keyword_llm_max_chars: int = 2400
    keyword_guard: str = "on"          # on | off：极性/否定、解释型意图、单文档收敛
    keyword_multi_doc: str = "off"     # off=一次直出只取一份文档
    # LLM：超时与重试必须显式，禁止依赖默认值
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 3
    llm_backoff_base_s: float = 1.0
    llm_backoff_max_s: float = 10.0
    wall_clock_budget_s: float = 60.0
    # 模型与端点（可被 LLM_BASE_URL / LLM_MODEL 覆盖）
    model: str = DEFAULT_MODEL
    api_base: str = DEFAULT_BASE_URL
    # 生产防护
    rate_limit_rps: float = 5.0
    rate_limit_burst: int = 10
    daily_token_budget: int = 200_000
    idempotency_ttl_s: int = 300
    canary_percent: int = 0
    canary_model: str = ""
    admin_token: str = ""
    # 多实例状态（为空则用进程内本地状态）
    redis_url: str = ""
    redis_timeout_s: float = 1.5
    redis_prefix: str = "rag"
    # 知识库版本与审批
    kb_store: str = "on"              # on | off
    kb_approval: str = "auto"         # auto=本机管理员直通，其他走审批 | on | off
    kb_dir: str = "data/kb"
    kb_seed_dir: str = "data/knowledge"   # 首次初始化版本库时的种子目录
    kb_async_reload: str = "on"       # on=上传后立即返回、后台重建索引 | off=同步重建
    # 目录监听间隔（秒）。0 表示关闭。默认开启是因为「改了文件不生效」是静默故障：
    # 用户不会怀疑索引，只会怀疑检索不准。5 秒是「改完再看结果」的自然节奏。
    kb_watch_seconds: int = 5
    kb_keep_versions: int = 30        # 保留最近 N 个版本（0=不清理），活动版本永不删除
    # 对外接口鉴权：为空=开放（仅按 IP 限流）；配置后 /api/ask* 必须带 Key
    api_keys: str = ""
    # 日志与成本
    log_sink: str = "file"            # file | stdout | both（stdout 供 Fluent Bit/Vector 采集）
    log_max_bytes: int = 16 * 1024 * 1024   # 单个 JSONL 超过即轮转（0=关闭）
    log_keep: int = 3                  # 保留的历史文件数
    token_price_per_1k: float = 0.0   # 单价需按供应商当期价格页填写；0=不计算金额


def load_settings() -> Settings:
    """把配置汇总成一个不可变快照。

    配置有两个来源，分工是写死的，不是历史包袱：
    - **设置面板**（写入 appconfig.json）：用户会在界面上改的东西，改完要重启服务；
      面板里显式清空的项不会回落到环境变量，否则用户清不干净。
    - **环境变量**：部署参数，尤其是密钥、监听、Redis 这类不适合放进界面文件的。
    优先级：面板 > 环境变量 > 本函数的默认值。

    全量变量清单在仓库根的 `.env.example`，由 `tools/gen_env_example.py` 从代码生成；
    `tests/test_config_fields.py` 会校验「代码读的变量」与「清单」一致，
    以及 Settings 的每个字段都真的被赋值——防止出现「设了没反应」和「改了名静默降级」。
    """
    retrieval = (_first_env("RETRIEVAL", default="vector") or "vector").strip().lower()
    if retrieval not in ("bm25", "hybrid", "vector", "embedding"):
        retrieval = "vector"
    expansion = (_first_env("QUERY_EXPANSION", default="auto") or "auto").strip().lower()
    if expansion not in ("off", "auto", "llm"):
        expansion = "auto"
    base = (_first_env("LLM_BASE_URL", default=DEFAULT_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")
    # 各检索器的分数尺度不同：BM25 是 0~20+ 原始分，hashing/embedding 归一化到 0~1。
    # 阈值必须分模式给默认值，否则换检索器会把所有问题打成「无法找到答案」。
    #
    # min_score 保持 1.27.0 的取值不动：实测发现 BM25 的原始分随**语料规模**变化
    # （6 篇 33 块时正确回答 9.5~33.9，5 块的小语料同样的问题只有 1.9），
    # 按一个语料标定出来的绝对值搬到另一份语料上就会把正常问题全拒掉。
    # 所以这里只给「归一化到 0~1」的模式设 hedge，BM25 需要使用者自己标定。
    default_min = {"embedding": "0.38", "hybrid": "0.30", "vector": "0.30"}.get(retrieval, "0.5")
    # 低于 hedge_score 仍作答，但加保留语气。0 表示不启用（BM25 这种量纲不固定的模式）。
    default_hedge = {"embedding": "0.80", "hybrid": "0.80", "vector": "0.80"}.get(retrieval, "0")
    keyword_mode = (_first_env("KEYWORD_MODE", default="on") or "on").strip().lower()
    if keyword_mode not in ("on", "off"):
        keyword_mode = "on"
    keyword_llm = (_first_env("KEYWORD_LLM", default="auto") or "auto").strip().lower()
    if keyword_llm not in ("off", "auto", "on"):
        keyword_llm = "auto"
    return Settings(
        channel=endpoint_label(base),
        top_k=int(_first_env("TOP_K", default="4")),
        min_score=float(_first_env("MIN_SCORE", default=default_min)),
        hedge_score=float(_first_env("HEDGE_SCORE", default=default_hedge)),
        retrieval=retrieval,
        rrf_k=int(_first_env("RRF_K", default="60")),
        query_expansion=expansion,
        profile=(_first_env("APP_PROFILE", default="finance") or "finance").strip().lower(),
        max_input_chars=int(_first_env("MAX_INPUT_CHARS", default="500")),
        max_context_chars=max(800, int(_first_env("MAX_CONTEXT_CHARS", default="6000"))),
        citation_strict=(_first_env("CITATION_STRICT", default="off") or "off").strip().lower()
        in ("on", "1", "true", "yes"),
        debug=(_first_env("DEBUG", default="off") or "off").strip().lower()
        in ("on", "1", "true", "yes"),
        keyword_mode=keyword_mode,
        keyword_llm=keyword_llm,
        keyword_index=_first_env("KEYWORD_INDEX", default="data/index/keywords.json"),
        keyword_top_n=max(1, min(8, int(_first_env("KEYWORD_TOP_N", default="3")))),
        keyword_llm_max_chars=int(_first_env("KEYWORD_LLM_MAX_CHARS", default="2400")),
        keyword_guard="off" if (_first_env("KEYWORD_GUARD", default="on") or "on").lower() == "off" else "on",
        keyword_multi_doc="on" if (_first_env("KEYWORD_MULTI_DOC", default="off") or "off").lower() == "on" else "off",
        llm_timeout_s=float(_first_env("LLM_TIMEOUT_S", default="30")),
        llm_max_retries=int(_first_env("LLM_MAX_RETRIES", default="3")),
        # 这两个字段之前只有 dataclass 默认值，load_settings 从不赋值：
        # 设 LLM_BACKOFF_BASE_S 完全无效，且没有任何地方能看出来。
        llm_backoff_base_s=float(_first_env("LLM_BACKOFF_BASE_S", default="1")),
        llm_backoff_max_s=float(_first_env("LLM_BACKOFF_MAX_S", default="10")),
        wall_clock_budget_s=float(_first_env("WALL_CLOCK_BUDGET_S", default="60")),
        model=_first_env("LLM_MODEL", default=DEFAULT_MODEL) or DEFAULT_MODEL,
        api_base=base,
        rate_limit_rps=float(_first_env("RATE_LIMIT_RPS", default="5")),
        rate_limit_burst=int(_first_env("RATE_LIMIT_BURST", default="10")),
        daily_token_budget=int(_first_env("DAILY_TOKEN_BUDGET", default="200000")),
        idempotency_ttl_s=int(_first_env("IDEMPOTENCY_TTL_S", default="300")),
        canary_percent=max(0, min(100, int(_first_env("CANARY_PERCENT", default="0")))),
        canary_model=_first_env("CANARY_MODEL", default=""),
        admin_token=_first_env("ADMIN_TOKEN", default=""),
        redis_url=_first_env("REDIS_URL", default=""),
        redis_timeout_s=float(_first_env("REDIS_TIMEOUT_S", default="1.5")),
        redis_prefix=_first_env("REDIS_PREFIX", default="rag"),
        kb_store=(_first_env("KB_STORE", default="on") or "on").strip().lower(),
        kb_approval=(_first_env("KB_APPROVAL", default="auto") or "auto").strip().lower(),
        kb_dir=_first_env("KB_DIR", default="data/kb"),
        kb_seed_dir=_first_env("KB_SEED_DIR", default="data/knowledge"),
        kb_async_reload=(_first_env("KB_ASYNC_RELOAD", default="on") or "on").strip().lower(),
        kb_watch_seconds=_env_int("KB_WATCH_SECONDS", default=5),
        kb_keep_versions=_env_int("KB_KEEP_VERSIONS", 30),
        api_keys=_first_env("API_KEYS", default="").strip(),
        log_sink=(_first_env("LOG_SINK", default="file") or "file").strip().lower(),
        log_max_bytes=_env_int("LOG_MAX_BYTES", 16 * 1024 * 1024),
        log_keep=min(9, _env_int("LOG_KEEP", 3, minimum=1)),
        token_price_per_1k=float(_first_env("TOKEN_PRICE_PER_1K", default="0")),
        embedding_provider=(_first_env("EMBEDDING_PROVIDER", default="none") or "none").strip().lower(),
        embedding_base_url=_first_env("EMBEDDING_BASE_URL", default=""),
        embedding_model=_first_env("EMBEDDING_MODEL", default=""),
        embedding_api_key=_first_env("EMBEDDING_API_KEY", "LLM_API_KEY", "DEEPSEEK_API_KEY", default=""),
        embedding_dim=int(_first_env("EMBEDDING_DIM", default="0")),
        embedding_batch=int(_first_env("EMBEDDING_BATCH", default="16")),
        embedding_timeout_s=float(_first_env("EMBEDDING_TIMEOUT_S", default="8")),
        embedding_max_retries=int(_first_env("EMBEDDING_MAX_RETRIES", default="2")),
        embedding_backoff_base_s=float(_first_env("EMBEDDING_BACKOFF_BASE_S", default="0.5")),
        embedding_backoff_max_s=float(_first_env("EMBEDDING_BACKOFF_MAX_S", default="4")),
        embedding_wall_clock_s=float(_first_env("EMBEDDING_WALL_CLOCK_S", default="30")),
        embedding_build_budget_s=float(_first_env("EMBEDDING_BUILD_BUDGET_S", default="600")),
        embedding_index_dir=_first_env("EMBEDDING_INDEX_DIR", default="data/index"),
        embedding_recall_k=int(_first_env("EMBEDDING_RECALL_K", default="48")),
        vector_store=(_first_env("VECTOR_STORE", default="auto") or "auto").strip().lower(),
        vector_ivf_nlist=int(_first_env("VECTOR_IVF_NLIST", default="64")),
        vector_ivf_nprobe=int(_first_env("VECTOR_IVF_NPROBE", default="8")),
    )


def api_key() -> str:
    """密钥：LLM_API_KEY 优先，兼容 DEEPSEEK_API_KEY。"""
    return _first_env("LLM_API_KEY", "DEEPSEEK_API_KEY", default="")
