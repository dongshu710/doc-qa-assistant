"""生产防护组件：限流、幂等、成本上限、审计、灰度与回滚。

这些能力不改变问答主链路，全部在服务层生效：
- 限流：按客户端 IP 的令牌桶，超限回 429 + Retry-After；
- 幂等：同一个 Idempotency-Key 在 TTL 内复用首次结果，避免重试造成重复计费；
- 成本上限：按天累计 token，达到上限后跳过模型调用、降级为抽取式；
- 审计：管理动作与问答摘要写入 logs/audit.jsonl（可同时输出 stdout 供采集）；
- 灰度：按请求 key 稳定分流到 CANARY_MODEL；
- 回滚：运行配置保留历史快照，可一键恢复上一版。

多实例：配置 `REDIS_URL` 后，限流、幂等、成本三类**共享状态**切到 Redis；
Redis 不可用时自动回退进程内实现（不是放行），并在 `/api/health` 与指标里暴露。
灰度与回滚是低频管理配置，仍以本地文件为准（多实例需共享卷或改配置中心）。
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from . import jsonl
from .redis_client import RedisClient, RedisError


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
        now = time.monotonic()
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
            self._items[key] = (time.monotonic() + self.ttl_s, value)


class CostBudget:
    """按天累计 token，落盘到 logs/cost.json。"""

    def __init__(self, daily_limit: int = 200_000, path: str = ""):
        self.daily_limit = max(0, int(daily_limit))
        self.path = path
        self._lock = threading.Lock()
        self._date = _today()
        self._used = 0
        # 写盘失败必须留痕：磁盘满时预算一直是 0，超限永远拦不住
        self.persist_failures = 0
        self.persist_error: str | None = None
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
            self.persist_error = None
        except OSError as exc:
            # 不抛：预算写不进去不该把问答打死；但计数与原因要能被健康检查看到，
            # 否则重启后用量归零，日上限形同不存在。
            self.persist_failures += 1
            self.persist_error = f"{type(exc).__name__}: {exc}"[:300]

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


class RedisRateLimiter:
    """Redis 令牌桶：Lua 原子执行，多实例共享同一份令牌。

    时间取 Redis 服务端 `TIME`，不依赖各实例本地时钟，避免机器间漂移把
    「5 rps」算成 3 rps 或 8 rps。Lua 里不做 TIME 调用（非确定性命令后写会
    触发脚本限制），由客户端先取时间再作为 ARGV 传入，误差 <1ms。
    """

    backend = "redis"
    LUA = """
local key = KEYS[1]
local rps = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = burst end
if ts == nil or now < ts then ts = now end
tokens = math.min(burst, tokens + (now - ts) * rps)
local allowed = 0
local retry = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry = (1 - tokens) / rps
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, math.ceil((burst / rps) * 1000) + 60000)
return {allowed, tostring(retry), tostring(math.floor(tokens))}
"""

    def __init__(self, client: RedisClient, rps: float = 5.0, burst: int = 10,
                 prefix: str = "rag"):
        self.client = client
        self.rps = max(0.1, float(rps))
        self.burst = max(1, int(burst))
        self.prefix = prefix

    def allow(self, key: str) -> RateDecision:
        now = self.client.execute("TIME")
        ts = float(now[0]) + float(now[1]) / 1_000_000
        res = self.client.eval(self.LUA, [f"{self.prefix}:rl:{key}"],
                               [self.rps, self.burst, f"{ts:.6f}"])
        if not isinstance(res, list) or len(res) < 3:
            raise RedisError(f"限流脚本返回异常: {res!r}")
        return RateDecision(allowed=bool(int(res[0])), retry_after=float(res[1]),
                            remaining=int(float(res[2])))


class RedisIdempotencyCache:
    """Redis 幂等存储：`SET NX PX` 首次写入生效，重启与跨实例都能复用。

    并发窗口：两个实例同时未命中会各算一次，只有先写入的结果被复用。
    这是「已完成结果复用」，不是严格 exactly-once；要彻底避免重复计费，
    需要把请求变成异步任务并加分布式锁，成本高于本场景收益。
    """

    backend = "redis"

    def __init__(self, client: RedisClient, ttl_s: int = 300, prefix: str = "rag"):
        self.client = client
        self.ttl_s = max(1, int(ttl_s))
        self.prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self.prefix}:idem:{key}"

    def get(self, key: str) -> dict | None:
        if not key:
            return None
        raw = self.client.get(self._key(key))
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def put(self, key: str, value: dict) -> None:
        if not key:
            return
        self.client.set(self._key(key), json.dumps(value, ensure_ascii=False),
                        ttl_s=self.ttl_s, nx=True)


class RedisCostBudget:
    """Redis 日 token 计数：`INCRBY` 原子累加，多实例共用一份预算。

    检查与累加不是同一事务：并发请求可能小幅超限（最多并发数 × 单次 token），
    这是可接受的成本上界；若要求硬上限，应改成 Lua 里「先查后加再返回」。
    """

    backend = "redis"

    def __init__(self, client: RedisClient, daily_limit: int = 200_000, prefix: str = "rag"):
        self.client = client
        self.daily_limit = max(0, int(daily_limit))
        self.prefix = prefix

    def _key(self) -> str:
        return f"{self.prefix}:cost:{_today()}"

    def _used(self) -> int:
        raw = self.client.get(self._key())
        try:
            return max(0, int(raw or 0))
        except (TypeError, ValueError):
            return 0

    @property
    def blocked(self) -> bool:
        return bool(self.daily_limit and self._used() >= self.daily_limit)

    def add(self, tokens) -> int:
        try:
            n = max(0, int(tokens or 0))
        except (TypeError, ValueError):
            n = 0
        if not n:
            return self._used()
        used = self.client.incrby(self._key(), n)
        self.client.expire(self._key(), 172800)
        return used

    def status(self) -> dict:
        used = self._used()
        remaining = max(0, self.daily_limit - used) if self.daily_limit else 0
        return {
            "date": _today(),
            "used": used,
            "limit": self.daily_limit,
            "remaining": remaining,
            "blocked": bool(self.daily_limit and used >= self.daily_limit),
        }


class _FailoverGuard:
    """Redis 主路径 + 本地兜底；失败后 30s 内不再打 Redis，避免每请求等超时。"""

    def __init__(self, name: str, primary, fallback):
        self.name = name
        self.primary = primary
        self.fallback = fallback
        self.last_error: str | None = None
        self.fallback_hits = 0
        self._retry_at = 0.0
        self._lock = threading.Lock()

    @property
    def backend(self) -> str:
        return getattr(self.primary, "backend", "local") if self.primary else "local"

    def _degrade(self, exc: Exception) -> None:
        with self._lock:
            self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            self._retry_at = time.monotonic() + 30
            self.fallback_hits += 1

    def call(self, method: str, *args, **kwargs):
        primary = self.primary
        if primary is not None and time.monotonic() >= self._retry_at:
            try:
                return getattr(primary, method)(*args, **kwargs)
            except (RedisError, OSError) as exc:
                self._degrade(exc)
        return getattr(self.fallback, method)(*args, **kwargs)


class RateLimitGuard(_FailoverGuard):
    def __init__(self, primary, fallback):
        super().__init__("rate", primary, fallback)
        self.rps = fallback.rps
        self.burst = fallback.burst

    def allow(self, key: str) -> RateDecision:
        return self.call("allow", key)


class IdempotencyGuard(_FailoverGuard):
    def __init__(self, primary, fallback):
        super().__init__("idempotency", primary, fallback)

    def get(self, key: str):
        return self.call("get", key)

    def put(self, key: str, value: dict) -> None:
        self.call("put", key, value)


class CostGuard(_FailoverGuard):
    def __init__(self, primary, fallback):
        super().__init__("cost", primary, fallback)
        self.daily_limit = fallback.daily_limit

    @property
    def blocked(self) -> bool:
        primary = self.primary
        if primary is not None and time.monotonic() >= self._retry_at:
            try:
                return bool(primary.blocked)
            except (RedisError, OSError) as exc:
                self._degrade(exc)
        return bool(self.fallback.blocked)

    def add(self, tokens) -> int:
        return int(self.call("add", tokens) or 0)

    def status(self) -> dict:
        return self.call("status")


class AuditLog:
    """追加写 JSONL；可选同时输出 stdout，供 Fluent Bit / Vector 采集。

    写失败不阻塞主流程，但会置 `last_error`，健康检查里可见——静默丢审计
    日志和没有审计日志一样危险。
    """

    def __init__(self, path: str, sink: str = "file", service: str = "doc-qa",
                 instance: str = "", max_bytes: int = 0, keep: int = 3):
        self.path = path
        self.sink = (sink or "file").strip().lower()
        self.max_bytes = max(0, int(max_bytes))
        self.keep = max(1, int(keep))
        self.service = service
        self.instance = instance or f"{socket.gethostname()}:{os.getpid()}"
        self.last_error: str | None = None
        self.write_failures = 0
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def write(self, action: str, **fields) -> None:
        record = {"ts": _now_iso(), "event": "audit", "service": self.service,
                  "instance": self.instance, "action": action}
        for key, value in fields.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                record[key] = value[:500] if isinstance(value, str) else value
            else:
                record[key] = str(value)[:500]
        line = json.dumps(record, ensure_ascii=False)
        if self.sink in ("stdout", "both"):
            try:
                with self._lock:
                    sys.stdout.write(line + "\n")
                    sys.stdout.flush()
            except OSError as exc:
                self.last_error = str(exc)
                self.write_failures += 1
        if self.sink in ("stdout",):
            return
        # 追加写 + 超限轮转：单文件大小有上界，尾读才有稳定的上界
        if not jsonl.append_line(self.path, line, self.max_bytes, self.keep):
            self.last_error = f"write failed: {self.path}"
            self.write_failures += 1

    def tail(self, limit: int = 20) -> list[dict]:
        """尾部 N 条（新 → 旧）。只读文件尾，不随日志总量变慢。"""
        return list(reversed(jsonl.tail_json(self.path, max(1, limit))))


class RuntimeConfig:
    """灰度比例与模型、回滚快照。文件优先于环境变量。"""

    def __init__(self, path: str, canary_percent: int = 0, canary_model: str = ""):
        self.path = path
        self._lock = threading.RLock()
        # 灰度比例写不进去 = 重启后回到环境变量默认值，用户以为改了其实没改
        self.persist_failures = 0
        self.persist_error: str | None = None
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
            self.persist_error = None
        except OSError as exc:
            self.persist_failures += 1
            self.persist_error = f"{type(exc).__name__}: {exc}"[:300]

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
        self.redis: RedisClient | None = None
        self.redis_error: str | None = None
        redis_url = getattr(settings, "redis_url", "") or ""
        if redis_url:
            client = None
            try:
                client = RedisClient(redis_url, getattr(settings, "redis_timeout_s", 1.5))
                client.execute("PING")
                self.redis = client
            except RedisError as exc:
                self.redis_error = f"{type(exc).__name__}: {exc}"[:300]
                if client:
                    client.close()

        prefix = getattr(settings, "redis_prefix", "rag")
        local_rate = RateLimiter(settings.rate_limit_rps, settings.rate_limit_burst)
        local_idem = IdempotencyCache(settings.idempotency_ttl_s)
        local_cost = CostBudget(settings.daily_token_budget, os.path.join(log_dir, "cost.json"))

        self.rate = RateLimitGuard(
            RedisRateLimiter(self.redis, local_rate.rps, local_rate.burst, prefix)
            if self.redis else None,
            local_rate,
        )
        self.idem = IdempotencyGuard(
            RedisIdempotencyCache(self.redis, settings.idempotency_ttl_s, prefix)
            if self.redis else None,
            local_idem,
        )
        self.cost = CostGuard(
            RedisCostBudget(self.redis, settings.daily_token_budget, prefix)
            if self.redis else None,
            local_cost,
        )
        self.audit = AuditLog(os.path.join(log_dir, "audit.jsonl"),
                              sink=getattr(settings, "log_sink", "file"),
                              max_bytes=getattr(settings, "log_max_bytes", 0),
                              keep=getattr(settings, "log_keep", 3))
        self.runtime = RuntimeConfig(os.path.join(log_dir, "runtime.json"),
                                     settings.canary_percent, settings.canary_model)

    @property
    def backend(self) -> str:
        return "redis" if self.redis else "local"

    def status(self) -> dict:
        return {
            "backend": self.backend,
            "redis_ok": bool(self.redis),
            "redis_error": self.redis_error,
            "fallbacks": {
                "rate": self.rate.fallback_hits,
                "idempotency": self.idem.fallback_hits,
                "cost": self.cost.fallback_hits,
            },
            "last_errors": {
                "rate": self.rate.last_error,
                "idempotency": self.idem.last_error,
                "cost": self.cost.last_error,
                "audit": self.audit.last_error,
            },
            "rate_limit_rps": self.rate.rps,
            "rate_limit_burst": self.rate.burst,
            "budget": self.cost.status(),
            "canary": self.runtime.status(),
            # 这几处原来都是 except OSError: pass：磁盘满时预算归零、灰度改成默认值、
            # 审计日志静默丢失，而外部看一切正常。计数放这里，健康检查能自动报警。
            "persist": {
                "cost": {"failures": self.cost.fallback.persist_failures,
                         "error": self.cost.fallback.persist_error},
                "canary": {"failures": self.runtime.persist_failures,
                           "error": self.runtime.persist_error},
                "audit": {"failures": self.audit.write_failures,
                          "error": self.audit.last_error},
            },
        }

    def close(self) -> None:
        if self.redis:
            self.redis.close()
