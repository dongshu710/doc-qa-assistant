"""对外接口的 API Key：解析、常量时间校验、脱敏展示。

配置格式（`API_KEYS`，逗号分隔）：
    API_KEYS=web:sk_live_xxx,ci:sk_test_yyy,mcp:sk_read_zzz:ro
三段式的最后一段是作用域：`ro` / `rw` / `admin`，省略等于 `rw`。
也接受不命名的 `sk_live_xxx`（名字取哈希前 6 位）。名字用于审计与按 Key 计成本；
密钥本身不进日志，只记录名字与末 4 位。

为什么要有作用域：给 MCP 客户端、仪表盘、只读机器人发全权 Key 是常见做法，
代价是「任何一处泄露 = 整库可写」。`ro` 只能读和提问，拿不到上传/删除/审批。

设计取舍：
- 不引入 JWT/OAuth：这是内部文档问答服务，调用方是脚本或后端，静态 Key + 轮换足够；
- 不做 HMAC 签名：签名要管时钟偏移与密钥分发，收益低于 TLS + 随机 Key；
- 比对用 `hmac.compare_digest`，避免逐字符比较泄露前缀。
"""
from __future__ import annotations

import hashlib
import hmac


def safe_equal(left: str, right: str) -> bool:
    """常量时间比较两个字符串。

    长度不同时也完整走一遍 digest（先各自哈希），不让调用方从耗时里读出「前缀对了几个字符」。
    统一走这里，避免有的地方用 == 有的地方用 compare_digest。
    """
    def digest(text: str) -> bytes:
        return hashlib.sha256(str(text or "").encode("utf-8")).digest()
    return hmac.compare_digest(digest(left), digest(right))


SCOPES = ("ro", "rw", "admin")

# 只读 Key 也允许的「读语义」POST：这些接口用 POST 只是因为要带请求体，
# 实际不改变任何状态（提问、检索调试、会话清理属于「我的上下文」，不算数据写入）。
READ_ONLY_POSTS = frozenset({
    "/api/ask", "/api/ask/stream", "/v1/chat/completions",
    "/dify/retrieval", "/api/search/debug",
    "/api/session/clear", "/api/feedback",
})


class ApiKeyStore:
    def __init__(self, raw: str = ""):
        self.keys: dict[str, str] = {}
        self.scopes: dict[str, str] = {}
        for item in (raw or "").split(","):
            entry = item.strip()
            if not entry:
                continue
            name, key, scope = "", "", "rw"
            parts = [part.strip() for part in entry.split(":")]
            if len(parts) >= 3 and parts[-1].lower() in SCOPES:
                # `名字:密钥:作用域`。末段恰好是作用域名时才按三段式解。
                scope = parts[-1].lower()
                name = parts[0]
                key = ":".join(parts[1:-1])
            elif len(parts) >= 2:
                # 与旧实现一致：只按**第一个**冒号切分，其余冒号属于密钥本身。
                # 曾经写成 `elif len(parts) == 2`，结果含冒号的老密钥全部失效——
                # 表现是「升级后所有带冒号的 Key 都 401」，而配置看起来没变。
                name, key = parts[0], ":".join(parts[1:])
            else:
                key = entry
            if not key:
                continue
            if not name:
                name = "key-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:6]
            # 同名多 Key 时后者覆盖前者：便于轮换期间新旧 Key 同时存在，
            # 但审计里仍按同一个调用方统计。
            self.keys[key] = name
            self.scopes[key] = scope

    @property
    def enabled(self) -> bool:
        return bool(self.keys)

    def identify(self, presented: str) -> tuple[str | None, str | None]:
        """返回 (名字, 错误)。错误为 missing / invalid。"""
        presented = (presented or "").strip()
        if not presented:
            return None, "missing"
        for key, name in self.keys.items():
            if hmac.compare_digest(key, presented):
                return name, None
        return None, "invalid"

    def identify_scope(self, presented: str) -> tuple[str | None, str, str | None]:
        """返回 (名字, 作用域, 错误)。作用域在 key 无效时给空串，避免调用方误当 rw。"""
        presented = (presented or "").strip()
        if not presented:
            return None, "", "missing"
        for key, name in self.keys.items():
            if hmac.compare_digest(key, presented):
                return name, self.scopes.get(key, "rw"), None
        return None, "", "invalid"

    @staticmethod
    def mask(key: str) -> str:
        key = key or ""
        return ("…" + key[-4:]) if len(key) >= 8 else "…"

    def describe(self) -> dict:
        # 不回名字：调用方标识属于内部信息，健康检查只需要知道「开没开」
        out = {"mode": "key" if self.enabled else "open", "keys": len(self.keys)}
        if self.enabled:
            # 只读 Key 的数量单独报：给出去几把只读钥匙，是运维该看得见的数字
            out["read_only"] = sum(1 for scope in self.scopes.values() if scope == "ro")
        return out
