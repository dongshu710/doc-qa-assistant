"""生产防护与示例问题的单元测试。

用法：python tests/test_guards.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.chunking import load_corpus  # noqa: E402
from src.guards import CostBudget, IdempotencyCache, RateLimiter, RuntimeConfig  # noqa: E402
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


def test_suggest() -> None:
    chunks = load_corpus(str(ROOT / "data" / "knowledge"))
    items = examples(chunks, 4)
    assert len(items) == 4 and all(len(q) > 4 for q in items)
    sim = similar(chunks, "今天天气怎么样")
    assert sim, "未命中时也应给出相似问题"
    print("suggest OK:", items[0], "|", sim[0])


if __name__ == "__main__":
    test_rate_limiter()
    test_idempotency()
    test_cost_budget()
    test_runtime_config()
    test_suggest()
    print("GUARDS OK")
