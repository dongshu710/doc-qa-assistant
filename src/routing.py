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
    ("/api/storage", API),
    ("/api/source", API),             # 文档原文
    ("/api/trace", API),              # 用户提问记录
    ("/api/feedback", API),
    ("/api/cases", API),
    ("/api/examples", API),
    ("/api/keywords", API),
    ("/api/metrics", API),
    ("/api/l3", API),
    ("/api/ask", API),
    ("/api/session", API),
    ("/api/reload", API),
    ("/mcp", API),                    # MCP over HTTP：能读写笔记，等同于 notes 接口
)

PAGE_PREFIXES = ("", "/ask", "/kb", "/files", "/index.html", "/insights",
                 "/dashboard", "/report", "/favicon.ico")


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


def is_page(path: str) -> bool:
    return path in PAGE_PREFIXES or not path.startswith("/api/")


def describe() -> list[dict]:
    """给测试与文档用：把表摊平成可断言的形状。"""
    return [{"prefix": prefix, "level": level} for prefix, level in RULES]
