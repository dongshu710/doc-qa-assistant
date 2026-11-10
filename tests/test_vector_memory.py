"""向量存储：float32 紧凑存储的内存上限与精度底线。

守三条：
1. 规模上去以后常驻内存必须远低于 `list[list[float]]`（容器本身才是大头）；
2. float32 带来的分数误差不影响排序——前 k 名的顺序必须与 float64 一致；
3. 零向量、维度不符这些边界不能因为换了容器就静默出错。

不联网、不依赖 numpy：只测纯 Python 兜底路径，那是零依赖环境的唯一路径。
"""

from __future__ import annotations

import math
import random
import sys
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.vector_store import PureFlatStore, l2_normalize  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def test_memory() -> None:
    print("同等规模下，紧凑存储的常驻内存要低一个量级")
    random.seed(11)
    count, dim = 1200, 256
    raw = [[random.uniform(-1, 1) for _ in range(dim)] for _ in range(count)]

    tracemalloc.start()
    store = PureFlatStore(dim)
    store.add(raw)
    compact, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tracemalloc.start()
    plain = [l2_normalize(vec) for vec in raw]
    expanded, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    ratio = expanded / compact
    print(f"     紧凑 {compact / 1024:.0f} KB / 列表 {expanded / 1024:.0f} KB（{ratio:.1f} 倍）")
    check("内存至少降为原来的三分之一", ratio > 3.0, f"实际 {ratio:.2f} 倍")
    check("存进去的条数正确", len(store) == count, str(len(store)))
    del plain


def test_precision() -> None:
    print("float32 的误差不能改变前 k 名顺序")
    random.seed(13)
    count, dim = 400, 128
    raw = [[random.uniform(-1, 1) for _ in range(dim)] for _ in range(count)]
    query = [random.uniform(-1, 1) for _ in range(dim)]

    store = PureFlatStore(dim)
    store.add(raw)
    got = store.search(query, 10)
    got_ids = [index for index, _ in got]

    # float64 参考实现：与旧路径逐元素相同
    normed = [l2_normalize(vec) for vec in raw]
    q = l2_normalize(query)
    expected = sorted(
        ((index, sum(a * b for a, b in zip(q, vec))) for index, vec in enumerate(normed)),
        key=lambda pair: pair[1], reverse=True)[:10]
    expected_ids = [index for index, _ in expected]

    check("前 10 名顺序一致", got_ids == expected_ids, f"{got_ids} vs {expected_ids}")
    worst = max(abs(got_score - exp_score) for (_, got_score), (_, exp_score)
                in zip(got, expected))
    check("分数误差小于 1e-5", worst < 1e-5, f"最大偏差 {worst:.2e}")


def test_edges() -> None:
    print("边界：零向量、维度不符、空库、长度为零的查询")
    store = PureFlatStore(4)
    zero = l2_normalize([0.0, 0.0, 0.0, 0.0], compact=True)
    check("零向量归一化后长度不变", len(zero) == 4, str(len(zero)))
    check("零向量结果全为 0", all(value == 0.0 for value in zero), str(list(zero)))

    store.add([[0.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]])
    scored = store.search([1.0, 0.0, 0.0, 0.0], 2)
    check("含零向量也能检索", len(scored) == 2, str(scored))
    check("零向量得分为 0", abs(dict(scored)[0]) < 1e-9, str(scored))

    try:
        store.add([[1.0, 2.0]])
    except ValueError as exc:
        check("维度不符抛 ValueError", "维度" in str(exc), str(exc))
    else:
        check("维度不符抛 ValueError", False, "没有抛错")

    empty = PureFlatStore(4)
    check("空库检索返回空", empty.search([1.0, 0.0, 0.0, 0.0], 3) == [], "非空")
    check("k<=0 返回空", store.search([1.0, 0.0, 0.0, 0.0], 0) == [], "非空")

    long_vec = l2_normalize([3.0, 4.0], compact=True)
    check("归一化后模长为 1", math.isclose(sum(v * v for v in long_vec), 1.0, rel_tol=1e-6),
          str(sum(v * v for v in long_vec)))


def test_disk_roundtrip() -> None:
    """同一个向量写盘再读回，打分不能变——float32 与 json 的 round(7) 要能对上。"""
    print("落盘再读回，分数一致")
    from src.vector_store import _chunk_key  # noqa: PLC0415

    random.seed(17)
    store = PureFlatStore(6)
    vector = [random.uniform(-1, 1) for _ in range(6)]
    store.add([vector])
    before = store.search(vector, 1)[0][1]

    written = [round(x, 7) for x in l2_normalize(vector)]
    reloaded = PureFlatStore(6)
    reloaded.add([written])
    after = reloaded.search(vector, 1)[0][1]
    check("写盘精度损失可忽略", abs(before - after) < 1e-6, f"{before:.8f} vs {after:.8f}")
    check("_chunk_key 仍可用", isinstance(_chunk_key, type(lambda: None)), "不可调用")


def main() -> int:
    test_memory()
    test_precision()
    test_edges()
    test_disk_roundtrip()
    print()
    if FAILED:
        print(f"VECTOR MEMORY FAILED: {FAILED}")
        return 1
    print("VECTOR MEMORY OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
