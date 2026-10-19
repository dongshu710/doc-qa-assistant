"""生产防护组件：限流、幂等、成本上限、审计、灰度与回滚。

这些能力不改变问答主链路，全部在服务层生效：
- 限流：按客户端 IP 的令牌桶，超限回 429 + Retry-After；
- 幂等：同一个 Idempotency-Key 在 TTL 内复用首次结果，避免重试造成重复计费；
- 成本上限：按天累计 token，达到上限后跳过模型调用、降级为抽取式；
- 审计：管理动作与问答摘要写入 logs/audit.jsonl；
- 灰度：按请求 key 稳定分流到 CANARY_MODEL；
- 回滚：运行配置保留历史快照，可一键恢复上一版。

所有状态都落在 logs/ 下，进程重启后仍可恢复。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _atomic_write(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


@dataclass
class RateDecision:
    allowed: bool
    retry_after: float
    remaining: int


class RateLimiter:
    """按 key（通常是客户端 IP）的令牌桶。"""

    def __init__(self, rps: float = 5.0, burst: int = 10, max_keys: int = 4096):
        self.rps = max(0.1, float(rps))
        self.burst = max(1, int(burst))
        self.max_keys = max_keys
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> RateDecision:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(self.burst), now))
            tokens = min(float(self.burst), tokens + (now - last) * self.rps)
            if tokens >= 1.0:
                tokens -= 1.0
                allowed, retry = True, 0.0
            else:
                allowed, retry = False, round((1.0 - tokens) / self.rps, 3)
            self._buckets[key] = (tokens, now)
            if len(self._buckets) > self.max_keys:
                # 只清理最久未活跃的一批，避免字典无限增长
                stale = sorted(self._buckets.items(), key=lambda kv: kv[1][1])[: self.max_keys // 4]
                for k, _v in stale:
                    self._buckets.pop(k, None)
            return RateDecision(allowed=allowed, retry_after=retry, remaining=int(tokens))


class IdempotencyCache:
    """进程内 TTL 缓存；单实例部署足够，多实例应换成 Redis。"""

    def __init__(self, ttl_s: int = 300, max_items: int = 512):
        self.ttl_s = max(1, int(ttl_s))
        self.max_items = max_items
        self._items: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        if not key:
            return None
        now = time.time()
        with self._lock:
            item = self._items.get(key)
            if not item:
                return None
            expires, value = item
            if expires <= now:
                self._items.pop(key, None)
                return None
            return value

    def put(self, key: str, value: dict) -> None:
        if not key:
            return
        with self._lock:
            if len(self._items) >= self.max_items:
                oldest = min(self._items.items(), key=lambda kv: kv[1][0])[0]
                self._items.pop(oldest, None)
            self._items[key] = (time.time() + self.ttl_s, value)


class CostBudget:
    """按天累计 token，落盘到 logs/cost.json。"""

    def __init__(self, daily_limit: int = 200_000, path: str = ""):
        self.daily_limit = max(0, int(daily_limit))
        self.path = path
        self._lock = threading.Lock()
        self._date = _today()
        self._used = 0
        self._load()

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        if data.get("date") == _today():
            self._used = max(0, int(data.get("tokens") or 0))

    def _save(self) -> None:
        if not self.path:
            return
        try:
            _atomic_write(self.path, {"date": self._date, "tokens": self._used, "updated_at": _now_iso()})
        except OSError:
            pass

    def _roll(self) -> None:
        today = _today()
        if today != self._date:
            self._date = today
            self._used = 0

    @property
    def blocked(self) -> bool:
        with self._lock:
            self._roll()
            return self.daily_limit > 0 and self._used >= self.daily_limit

    def add(self, tokens) -> int:
        try:
            n = max(0, int(tokens or 0))
        except (TypeError, ValueError):
            n = 0
        if not n:
            return 0
        with self._lock:
            self._roll()
            self._used += n
            self._save()
            return self._used

    def status(self) -> dict:
        with self._lock:
            self._roll()
            remaining = max(0, self.daily_limit - self._used) if self.daily_limit else 0
            return {
                "date": self._date,
                "used": self._used,
                "limit": self.daily_limit,
                "remaining": remaining,
                "blocked": bool(self.daily_limit and self._used >= self.daily_limit),
            }


class AuditLog:
    """追加写 JSONL；写失败不阻塞主流程。"""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def write(self, action: str, **fields) -> None:
        record = {"ts": _now_iso(), "action": action}
        for key, value in fields.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                record[key] = value[:500] if isinstance(value, str) else value
            else:
                record[key] = str(value)[:500]
        try:
            with self._lock, open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def tail(self, limit: int = 20) -> list[dict]:
        rows: list[dict] = []
        if not os.path.exists(self.path):
            return rows
        try:
            with open(self.path, encoding="utf-8") as f:
                lines = [line for line in f.read().splitlines() if line.strip()][-max(1, limit):]
        except OSError:
            return rows
        for line in lines:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(rows))


class RuntimeConfig:
    """灰度比例与模型、回滚快照。文件优先于环境变量。"""

    def __init__(self, path: str, canary_percent: int = 0, canary_model: str = ""):
        self.path = path
        self._lock = threading.RLock()
        self._data = {
            "revision": 0,
            "canary_percent": max(0, min(100, int(canary_percent))),
            "canary_model": (canary_model or "").strip(),
            "updated_at": _now_iso(),
            "history": [],
        }
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict):
            self._data.update({
                "revision": int(data.get("revision") or 0),
                "canary_percent": max(0, min(100, int(data.get("canary_percent") or 0))),
                "canary_model": str(data.get("canary_model") or ""),
                "updated_at": data.get("updated_at") or _now_iso(),
                "history": list(data.get("history") or [])[-20:],
            })

    def _save(self) -> None:
        try:
            _atomic_write(self.path, self._data)
        except OSError:
            pass

    def _snapshot(self) -> dict:
        return {
            "canary_percent": self._data["canary_percent"],
            "canary_model": self._data["canary_model"],
            "updated_at": self._data["updated_at"],
        }

    def update(self, canary_percent=None, canary_model=None, note: str = "") -> dict:
        with self._lock:
            self._data["history"].append({**self._snapshot(), "archived_at": _now_iso(), "note": note})
            self._data["history"] = self._data["history"][-20:]
            if canary_percent is not None:
                self._data["canary_percent"] = max(0, min(100, int(canary_percent)))
            if canary_model is not None:
                self._data["canary_model"] = str(canary_model).strip()
            self._data["revision"] = int(self._data["revision"]) + 1
            self._data["updated_at"] = _now_iso()
            self._save()
            return self.status()

    def rollback(self) -> dict:
        with self._lock:
            history = self._data.get("history") or []
            if not history:
                return {**self.status(), "rolled_back": False, "reason": "没有可回滚的历史版本"}
            prev = history.pop()
            self._data.update({
                "canary_percent": int(prev.get("canary_percent") or 0),
                "canary_model": str(prev.get("canary_model") or ""),
                "history": history,
                "revision": int(self._data["revision"]) + 1,
                "updated_at": _now_iso(),
            })
            self._save()
            return {**self.status(), "rolled_back": True, "restored_from": prev.get("updated_at")}

    def status(self) -> dict:
        with self._lock:
            return {
                "revision": self._data["revision"],
                "canary_percent": self._data["canary_percent"],
                "canary_model": self._data["canary_model"],
                "updated_at": self._data["updated_at"],
                "history": len(self._data.get("history") or []),
            }

    def pick_model(self, key: str) -> str | None:
        """按 key 稳定分流；同一 key 在比例不变时结果一致。"""
        with self._lock:
            percent = self._data["canary_percent"]
            model = self._data["canary_model"]
        if percent <= 0 or not model:
            return None
        bucket = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 100
        return model if bucket < percent else None


class Guards:
    def __init__(self, settings, log_dir: str):
        self.rate = RateLimiter(settings.rate_limit_rps, settings.rate_limit_burst)
        self.idem = IdempotencyCache(settings.idempotency_ttl_s)
        self.cost = CostBudget(settings.daily_token_budget, os.path.join(log_dir, "cost.json"))
        self.audit = AuditLog(os.path.join(log_dir, "audit.jsonl"))
        self.runtime = RuntimeConfig(os.path.join(log_dir, "runtime.json"),
                                     settings.canary_percent, settings.canary_model)

    def status(self) -> dict:
        return {"rate_limit_rps": self.rate.rps, "rate_limit_burst": self.rate.burst,
                "budget": self.cost.status(), "canary": self.runtime.status()}
