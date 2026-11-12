"""路由鉴权表：每条路径该不该要 Key / 管理员，只在这里登记一次。

为什么需要一张表：
原来每个 handler 自己决定要不要鉴权，结果是知识库的上传/删除接口**完全没有鉴权**
（`approve` 要管理员，同一目录下的 `upload` 却谁都能调），笔记和会话却加了保护。
这不是疏忽，是结构问题——新增接口时「记得加检查」从来不是可靠约束。

现在的规则：
- 未登记的 `/api/*` 一律按 `api` 处理（配了 `API_KEYS` 就要 Key）。默认收紧，
  忘了登记最多是「多要一个 Key」，不会变成「谁都能读原文」。
- 只有显式登记为 `open` 的才真开放：设置（Key 配错时的回退通道）、健康检查、
  更新检查、契约文档。
- 最长前缀优先，`/api/kb/approve` 的管理员要求不会被 `/api/kb` 覆盖。
"""
from __future__ import annotations

OPEN = "open"
API = "api"
ADMIN = "admin"

# 顺序无关，匹配按前缀长度取最长
RULES: tuple[tuple[str, str], ...] = (
    ("/api/settings", OPEN),          # Key 配错时唯一的回退通道
    ("/api/health", OPEN),            # 只暴露版本/块数/警告，不含正文
    ("/api/update", OPEN),            # 只查版本号，不下载不安装
    ("/openapi.json", OPEN),
    ("/tools.json", OPEN),            # function calling 清单，本身就是给外部看的
    ("/metrics", ADMIN),              # 含成本与 Key 标签的哈希前缀
    ("/api/audit", ADMIN),            # 审计里有提问原文
    ("/api/admin", ADMIN),
    ("/api/kb/approve", ADMIN),       # 审批会生成新版本，等于改语料
    ("/api/kb/reject", ADMIN),
    ("/api/kb/rollback_doc", ADMIN),
    ("/api/kb", API),                 # 版本列表与 diff 也是语料
    ("/api/knowledge", API),          # 上传/删除都在这里
    ("/api/notes", API),
    ("/api/threads", API),
    ("/api/files", API),
    # `/api/storage` 本身没有 handler，只有 usage/backups/backup/cleanup 四个子端点；
    # 曾经在这里登记过前缀，表里就出现了一个不存在的端点（鉴权表是契约的单一来源，
    # 登记不存在的路径只会误导维护者）。子端点不登记也照样是 API——未登记的
    # `/api/*` 默认收紧，少写一行不会放宽任何东西。
    ("/api/source", API),             # 文档原文
    ("/api/trace", API),              # 用户提问记录
    ("/api/feedback", API),
    ("/api/cases", API),
    ("/api/examples", API),
    ("/api/keywords", API),
    ("/api/search", API),   # 检索调试：返回原文片段与分数
    # 重建关键词会重写索引、还可能调模型补词，handler 里本来就要求 admin。
    # 表里不标就会让 describe() 与测试以为它是 api 级——权限文档直接写错。
    ("/api/keywords/rebuild", ADMIN),
    ("/api/metrics", API),
    ("/api/l3", API),
    ("/api/ask", API),
    ("/api/session", API),
    ("/api/reload", API),
    ("/mcp", API),                    # MCP over HTTP：能读写笔记，等同于 notes 接口
    # Dify 外部知识库适配。必须显式登记：它不在 /api/ 下，不登记会落到默认 open，
    # 等于把「按问题检索语料原文」这个能力对全网敞开（单机也一样，任意网页都能请求回环）。
    # 实际凭据用 `Authorization: Bearer <API_KEY>`，与 Dify 面板里填的密钥是同一个。
    ("/dify", API),
    # OpenAI 兼容面（给 SDK / LiteLLM / LangChain 用）。必须显式登记：
    # 它不在 /api/ 下，不登记会落到默认 open——等于把「按问题检索语料并生成」
    # 对全网敞开，比 /dify（只检索不生成）更严重。
    ("/v1", API),
)

# 页面清单只登记一次：`_get_page_html` 按这里的键去取 HTML。
# 以前 `PAGE_PREFIXES`（本文件）与 `read.py` 的 if/elif 各写一遍页面路径，
# 加一个页面要改两处，漏一处的表现是「收藏夹里的地址突然 404」。
PAGE_ROUTES: dict[str, str] = {
    "/ask": "ask",
    # 笔记与附件。1.37.0 起从 /files 改名提级：内容是「我存过的记忆」，
    # 叫「文件」会让人以为是上传区，而它其实是这个项目最不一样的资产。
    "/notes": "files",
    "/kb": "kb",
    # 汇报页：既是展示页，也是管理台入口。内容随数据变，所以由 handler 实时渲染
    # （`?download=1` 走同一个路径返回附件，不新增 API 端点）。
    "/report": "report",
    # 检索调试台：只读，用来解释「为什么没有答案」
    "/debug": "debug",
}
# 旧入口：只做跳转，收藏夹里的老地址不至于 404
PAGE_ALIASES: tuple[str, ...] = ("/", "/index.html", "/insights", "/dashboard")

# 改名后的旧地址 → 新地址。单独一张表而不是塞进 PAGE_ALIASES：
# 那张表是「所有旧入口都回落到问答页」的语义，这里要的是**精确对应**的跳转。
PAGE_MOVED: dict[str, str] = {"/files": "/notes"}


def _matches(path: str, prefix: str) -> bool:
    if not prefix:
        return path == "/"
    return path == prefix or path.startswith(prefix + "/")


def level_for(path: str) -> str:
    """返回该路径要求的鉴权等级；未登记的 API 默认收紧。"""
    best = ""
    level = ""
    for prefix, rule in RULES:
        if _matches(path, prefix) and len(prefix) > len(best):
            best, level = prefix, rule
    if level:
        return level
    if path.startswith("/api/"):
        return API
    return OPEN


def describe() -> list[dict]:
    """给测试与文档用：把表摊平成可断言的形状。"""
    return [{"prefix": prefix, "level": level} for prefix, level in RULES]


# ---------- 方法表：只用于「方法用错时报 405 而不是 404」 ----------
# 为什么不再手写：手写的表一定会跟真实路由漂移。上一版这里有一张
# `_EXTRA_METHODS` 补丁表（列 OpenAPI 没登记但真实存在的端点），漂了两处：
# `/api/storage/usage` 与 `/api/storage/cleanup` 早已没有实现，
# 而真存在的 `/api/storage/restore` 反倒没登记——对 `GET /api/storage/restore`
# 会回 404（应该 405）。现在补丁表已删除，OpenAPI 补齐了全部端点，
# 路径与方法只有这一份来源。
# 只在 dispatch 已经判定「没有这个路由」时才查这张表，所以即使取错了，
# 最坏结果是 404 变 405，不会把一个本来能用的请求挡掉。
_SPEC_METHODS: dict[str, set[str]] | None = None


def _spec_methods() -> dict[str, set[str]]:
    global _SPEC_METHODS
    if _SPEC_METHODS is None:
        table: dict[str, set[str]] = {}
        try:
            from .openapi import build_spec
            spec = build_spec("0.0.0", {"mode": "open"}, "", "vector")
            for path, ops in (spec.get("paths") or {}).items():
                table[path] = {m.upper() for m in ops
                               if m.lower() in ("get", "post", "put", "patch", "delete")}
        except Exception:      # noqa: BLE001 —— 规格生成失败不该影响请求处理
            table = {}
        _SPEC_METHODS = table
    return _SPEC_METHODS


def _match_template(template: str, path: str) -> bool:
    left = template.strip("/").split("/")
    right = path.strip("/").split("/")
    if len(left) != len(right):
        return False
    return all(a.startswith("{") or a == b for a, b in zip(left, right))


def allowed_methods(path: str) -> set[str] | None:
    """这个路径允许哪些方法；完全没登记就返回 None（调用方按 404 处理）。"""
    table = _spec_methods()
    if path in table:
        return table[path]
    for template, methods in table.items():
        if "{" in template and _match_template(template, path):
            return methods
    return None
