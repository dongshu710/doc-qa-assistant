"""多实例防护状态测试：限流 / 幂等 / 成本在 Redis 上跨实例一致。

用法：
    REDIS_URL=redis://127.0.0.1:6379/0 python tests/test_redis_guards.py
未设置 REDIS_URL 时依次探测 6379、6399；都没有则打印 SKIP 并退出 0
（CI 里通过 service 容器提供 Redis，此时必须真跑，不允许静默跳过）。

测试会使用独立前缀并在结束时删除，不会污染已有键。
"""
import dataclasses
import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_settings  # noqa: E402
from src.guards import AuditLog, Guards  # noqa: E402
from src.redis_client import RedisClient, RedisError  # noqa: E402


def find_redis() -> str:
    candidates = [os.getenv("REDIS_URL", "")]
    candidates += ["redis://127.0.0.1:6379/0", "redis://127.0.0.1:6399/0"]
    for url in candidates:
        if not url:
            continue
        client = RedisClient(url, 1.0)
        if client.ping():
            client.close()
            return url
    return ""


def make_guards(url: str, prefix: str, tmp: str, **overrides) -> Guards:
    settings = dataclasses.replace(
        load_settings(),
        redis_url=url,
        redis_prefix=prefix,
        redis_timeout_s=1.0,
        rate_limit_rps=1.0,
        rate_limit_burst=1,
        daily_token_budget=100,
        idempotency_ttl_s=30,
        log_sink="file",
        **overrides,
    )
    return Guards(settings, tmp)


def test_cross_instance(url: str, prefix: str, tmp: str) -> None:
    a = make_guards(url, prefix, tmp)
    b = make_guards(url, prefix, tmp)
    assert a.backend == "redis" and b.backend == "redis", (a.status(), b.status())

    # 限流：两个实例共享同一个令牌桶
    assert a.rate.allow("1.2.3.4").allowed is True
    denied = b.rate.allow("1.2.3.4")
    assert denied.allowed is False and denied.retry_after > 0
    print("cross-instance rate limit OK")

    # 幂等：A 写入，B 读到同一结果
    a.idem.put("k-1", {"trace_id": "t-1", "answer": "ok"})
    assert b.idem.get("k-1")["trace_id"] == "t-1"
    print("cross-instance idempotency OK")

    # 成本：A/B 各记一笔，总额与拦截状态一致
    a.cost.add(60)
    b.cost.add(50)
    assert b.cost.blocked is True
    assert b.cost.status()["used"] == 110, b.cost.status()
    print("cross-instance cost budget OK")

    # Redis 不可用：回退本地，不放行也不崩
    dead = make_guards("redis://127.0.0.1:6398/0", prefix + ":dead", tmp)
    assert dead.backend == "local" and dead.redis_error
    assert dead.rate.allow("ip").allowed is True
    dead.idem.put("k", {"trace_id": "local"})
    assert dead.idem.get("k")["trace_id"] == "local"
    print("redis outage fallback OK")

    a.close()
    b.close()
    dead.close()


def test_audit_json(tmp: str) -> None:
    path = os.path.join(tmp, "audit.jsonl")
    log = AuditLog(path, sink="file")
    log.write("ask", trace_id="t", request_id="r", behavior="answer", tokens=12)
    rows = log.tail(1)
    assert rows and rows[0]["event"] == "audit" and rows[0]["service"] == "doc-qa"
    assert rows[0]["request_id"] == "r" and rows[0]["instance"]
    print("audit record OK")


def test_bad_url() -> None:
    try:
        RedisClient("http://127.0.0.1:6379", 0.5)
    except RedisError:
        print("bad scheme rejected OK")
    else:
        raise AssertionError("非 redis:// scheme 必须报错")


if __name__ == "__main__":
    test_bad_url()
    url = find_redis()
    if not url:
        print("SKIP: 未找到可用 Redis（设置 REDIS_URL 后重跑）")
        sys.exit(0)
    prefix = f"ragtest:{uuid.uuid4().hex[:8]}"
    client = RedisClient(url, 1.0)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            test_cross_instance(url, prefix, tmp)
            test_audit_json(tmp)
    finally:
        keys = client.execute("KEYS", prefix + "*") or []
        if keys:
            client.execute("DEL", *keys)
        client.close()
    print("ALL REDIS GUARD TESTS PASSED")
