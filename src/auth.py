"""对外接口的 API Key：解析、常量时间校验、脱敏展示。

配置格式（`API_KEYS`，逗号分隔）：
    API_KEYS=web:sk_live_xxx,ci:sk_test_yyy
也接受不命名的 `sk_live_xxx`（名字取哈希前 6 位）。名字用于审计与按 Key 计成本；
密钥本身不进日志，只记录名字与末 4 位。

设计取舍：
- 不引入 JWT/OAuth：这是内部文档问答服务，调用方是脚本或后端，静态 Key + 轮换足够；
- 不做 HMAC 签名：签名要管时钟偏移与密钥分发，收益低于 TLS + 随机 Key；
- 比对用 `hmac.compare_digest`，避免逐字符比较泄露前缀。
"""
from __future__ import annotations

import hashlib
import hmac


class ApiKeyStore:
    def __init__(self, raw: str = ""):
        self.keys: dict[str, str] = {}
        for item in (raw or "").split(","):
            entry = item.strip()
            if not entry:
                continue
            if ":" in entry:
                name, key = entry.split(":", 1)
                name = name.strip()
                key = key.strip()
            else:
                key = entry
                name = ""
            if not key:
                continue
            if not name:
                name = "key-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:6]
            # 同名多 Key 时后者覆盖前者：便于轮换期间新旧 Key 同时存在，
            # 但审计里仍按同一个调用方统计。
            self.keys[key] = name

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

    @staticmethod
    def mask(key: str) -> str:
        key = key or ""
        return ("…" + key[-4:]) if len(key) >= 8 else "…"

    def public_names(self) -> list[str]:
        return sorted(set(self.keys.values()))

    def describe(self) -> dict:
        # 不回名字：调用方标识属于内部信息，健康检查只需要知道「开没开」
        return {"mode": "key" if self.enabled else "open", "keys": len(self.keys)}
