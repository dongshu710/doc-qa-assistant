"""生产防护与示例问题的单元测试。

用法：python tests/test_guards.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.chunking import load_corpus  # noqa: E402
from src.guards import (AuditLog, CostBudget, IdempotencyCache, RateLimiter,  # noqa: E402
                        RuntimeConfig)
from src.suggest import examples, similar  # noqa: E402


def test_rate_limiter() -> None:
    limiter = RateLimiter(rps=1, burst=1)
    assert limiter.allow("ip-a").allowed
    denied = limiter.allow("ip-a")
    assert not denied.allowed and denied.retry_after > 0
    assert limiter.allow("ip-b").allowed
    print("rate limiter OK")


def test_idempotency() -> None:
    cache = IdempotencyCache(ttl_s=60)
    assert cache.get("k") is None
    cache.put("k", {"trace_id": "t1"})
    assert cache.get("k")["trace_id"] == "t1"
    assert cache.get("") is None
    print("idempotency OK")


def test_cost_budget() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "cost.json")
        budget = CostBudget(daily_limit=100, path=path)
        assert not budget.blocked
        budget.add(60)
        assert budget.status()["remaining"] == 40
        budget.add(50)
        assert budget.blocked
        reloaded = CostBudget(daily_limit=100, path=path)
        assert reloaded.status()["used"] == 110
    print("cost budget OK")


def test_runtime_config() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "runtime.json")
        runtime = RuntimeConfig(path, canary_percent=0, canary_model="")
        assert runtime.pick_model("x") is None
        runtime.update(canary_percent=100, canary_model="model-b")
        assert runtime.pick_model("x") == "model-b"
        runtime.update(canary_percent=0, canary_model="")
        assert runtime.status()["revision"] == 2
        rolled = runtime.rollback()
        assert rolled["rolled_back"] and rolled["canary_model"] == "model-b"
        again = RuntimeConfig(path, 0, "")
        assert again.status()["canary_model"] == "model-b"
    print("runtime config / rollback OK")


def test_persist_failure_visible() -> None:
    """写盘失败必须留痕。

    原来 CostBudget._save、RuntimeConfig._save、AuditLog.write 三处都是
    `except OSError: pass`：磁盘满时预算一直是 0（日上限形同不存在）、
    灰度改完重启回默认值、审计日志静默丢失，而外部看一切正常。
    """
    from types import SimpleNamespace

    from src.guards import AuditLog, Guards

    with tempfile.TemporaryDirectory() as tmp:
        # 把目标路径占成目录：写入必然失败，又不会真的弄坏磁盘
        blocked = Path(tmp) / "blocked"
        blocked.mkdir()

        budget = CostBudget(daily_limit=100, path=str(blocked))
        budget.add(10)
        assert budget.persist_failures == 1, budget.persist_failures
        assert budget.persist_error, "只计数不记原因，排查时还是瞎猜"

        runtime = RuntimeConfig(str(blocked), 0, "")
        runtime.update(canary_percent=5, canary_model="m")
        assert runtime.persist_failures >= 1
        assert runtime.persist_error

        audit = AuditLog(str(blocked))
        audit.write("test.event", note="x")
        assert audit.write_failures >= 1
        assert audit.last_error

        settings = SimpleNamespace(
            redis_url="", redis_prefix="rag", rate_limit_rps=5, rate_limit_burst=10,
            idempotency_ttl_s=300, daily_token_budget=100, log_sink="file",
            log_max_bytes=0, log_keep=3, canary_percent=0, canary_model="",
            redis_timeout_s=1.5,
        )
        guards = Guards(settings, str(Path(tmp) / "logs"))
        guards.cost.fallback.path = str(blocked)   # 让这一份也写不进去
        guards.cost.add(5)
        persist = guards.status()["persist"]
        assert persist["cost"]["failures"] == 1, persist
        assert persist["cost"]["error"], persist
        assert persist["audit"]["failures"] == 0, persist
    print("persist failure visible OK")


def test_suggest() -> None:
    chunks = load_corpus(str(ROOT / "data" / "knowledge"))
    items = examples(chunks, 4)
    assert len(items) == 4 and all(len(q) > 4 for q in items)
    sim = similar(chunks, "今天天气怎么样")
    assert sim, "未命中时也应给出相似问题"
    print("suggest OK:", items[0], "|", sim[0])


def test_cost_throttle() -> None:
    """计数在内存里，落盘按节流推——但 flush 与超限必须立刻落。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "cost.json")
        budget = CostBudget(daily_limit=10_000, path=path)
        for _ in range(5):
            budget.add(7)
        assert budget.status()["used"] == 35, "内存里的计数必须立刻准确"
        on_disk = CostBudget(daily_limit=10_000, path=path).status()["used"]
        assert on_disk < 35, f"连续 add 不该每次都写盘（磁盘上是 {on_disk}）"
        budget.flush()
        assert CostBudget(daily_limit=10_000, path=path).status()["used"] == 35, "flush 要落全"
        print("cost throttle OK：内存 35 / 落盘前", on_disk)


def test_cost_over_limit_flushes() -> None:
    """超限那一刻必须落盘：否则重启后用量归零，日上限形同不存在。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "cost.json")
        budget = CostBudget(daily_limit=100, path=path)
        budget.flush()                       # 先把时间戳推到现在
        budget.add(60)
        budget.flush()                       # 落一次，重置节流窗口
        budget.add(50)                       # 这一刻超限
        assert budget.blocked
        assert CostBudget(daily_limit=100, path=path).status()["used"] == 110
        print("cost over-limit flush OK")


def test_audit_mask_pii() -> None:
    """审计里的证件类数字要打码；普通数字不能被误伤到失去意义。"""
    masked = AuditLog.mask_pii("我的手机 13812345678，身份证 11010519900307123X，卡号 6222021234567890123")
    assert "13812345678" not in masked, masked
    assert "11010519900307123X" not in masked, masked
    assert "6222021234567890123" not in masked, masked
    assert "138****5678" in masked, masked
    assert "110****123X" in masked, masked
    plain = "起购金额 1 元，封闭期 90 天，编号 20261031"
    assert AuditLog.mask_pii(plain) == plain, AuditLog.mask_pii(plain)
    print("audit mask PII OK:", masked)


if __name__ == "__main__":
    test_rate_limiter()
    test_idempotency()
    test_cost_budget()
    test_cost_throttle()
    test_cost_over_limit_flushes()
    test_audit_mask_pii()
    test_runtime_config()
    test_persist_failure_visible()
    test_suggest()
    print("GUARDS OK")
