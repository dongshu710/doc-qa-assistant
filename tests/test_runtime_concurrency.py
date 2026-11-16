"""运行期并发：成本落盘、索引代次、查询缓存、笔记索引重建。

（与 `test_concurrency.py` 不是一回事：那份测的是「文件写入的乐观锁」，
这份测的是服务进程内的共享状态。）

这四条的共同点是「只在并发下错，而且不报错」：

- 成本预算在锁内写盘 → 慢盘上所有提问串在同一个锁上（表现为「偶尔全体变慢」）；
- 索引分四次赋值 → 读到「新 chunks + 旧 retriever」（表现为引用指向另一份文档）；
- 查询缓存裸 dict + 缺单飞 → 同题并发各付一次 embedding；
- 笔记索引 `rebuild` 不持锁 + 固定临时名 → 两个写者交错写出半行 JSON。

因此这里都用「刻意制造的时序」去撞它们，而不是断言某个函数被调用。
"""
from __future__ import annotations

import collections
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import guards  # noqa: E402
from src.notes.search import NoteSearcher  # noqa: E402
from src.pipeline import IndexSnapshot, RAGPipeline  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


# ---------------- 15：成本预算落盘不在锁内 ----------------
def test_cost_off_lock() -> None:
    print("成本预算：写盘不占计数锁")
    tmp = tempfile.mkdtemp(prefix="cost_")
    path = str(Path(tmp) / "cost.json")
    budget = guards.CostBudget(daily_limit=10_000, path=path)

    entered = threading.Event()
    release = threading.Event()
    original = guards._atomic_write

    def slow_write(target, data):
        entered.set()
        release.wait(3.0)          # 把「慢盘」的窗口放大到能观测
        original(target, data)

    guards._atomic_write = slow_write
    try:
        worker = threading.Thread(target=lambda: budget.add(100), daemon=True)
        worker.start()
        check("第一次 add 触发了落盘", entered.wait(2.0), "没进到写盘")

        began = time.monotonic()
        budget.add(5)              # 落盘还卡着，这一次必须立刻返回
        elapsed = time.monotonic() - began
        check("写盘进行中，另一次 add 不被阻塞", elapsed < 0.5, f"{elapsed:.3f}s")

        release.set()
        worker.join(5)
        check("两次 add 都计入了", budget.status()["used"] == 105, str(budget.status()))
    finally:
        guards._atomic_write = original

    # 水位线：先写大数、再拿旧快照来写，不能把用量写回去
    budget._persist(("2026-01-01", 500))
    budget._persist(("2026-01-01", 120))
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    check("旧快照不会覆盖已落盘的大数", saved["tokens"] == 500, str(saved))


# ---------------- 16：索引代次原子替换 ----------------
def test_index_snapshot() -> None:
    print("索引代次：读侧永远看到同一代")
    pipe = object.__new__(RAGPipeline)
    pipe._swap_lock = threading.RLock()

    class Gen:
        def __init__(self, tag: str, chunks: list):
            self.tag = tag
            self.chunks = chunks

    gens = [Gen(f"g{i}", [f"c{i}a", f"c{i}b"]) for i in range(2)]
    pipe._index = IndexSnapshot(chunks=gens[0].chunks, vocabulary=set(),
                                retriever=gens[0], keywords=None, knowledge_dir="/a")

    stop = threading.Event()

    def swapper() -> None:
        i = 0
        while not stop.is_set():
            gen = gens[i % 2]
            pipe._swap_index("/a", gen.chunks, gen, None)
            i += 1

    thread = threading.Thread(target=swapper, daemon=True)
    thread.start()
    mixed = 0
    reads = 0
    began = time.monotonic()
    while time.monotonic() - began < 0.6:
        snap = pipe._index
        reads += 1
        # 同一代里 retriever.chunks 必须与 snap.chunks 是同一个对象
        if snap.retriever.chunks is not snap.chunks:
            mixed += 1
    stop.set()
    thread.join(5)
    check(f"并发读写 {reads} 次没有跨代组合", mixed == 0, f"{mixed} 次混用")
    check("确实发生了换代（不是空跑）", reads > 100, str(reads))

    # 属性 setter 仍然可用（测试注入假检索器依赖它）。
    # 注意判据是「chunks 没被这次写带走」，不是「等于某一代」——换代线程刚停，
    # 此刻是哪一代取决于最后一次 swap，跟这里无关。
    before = pipe._index.chunks
    pipe.retriever = gens[1]
    check("retriever 可写（整代替换）", pipe._index.retriever is gens[1], str(pipe._index.retriever))
    check("写 retriever 不动 chunks", pipe._index.chunks is before, "chunks 被带跑了")


# ---------------- 17：同题并发只发一次 embedding ----------------
def test_single_flight() -> None:
    print("查询向量：同题并发只算一次")
    from src.retriever import EmbeddingRetriever

    class Provider:
        model = "fake"
        dim = 4

        def __init__(self):
            self.calls = 0
            self._lock = threading.Lock()

        def embed(self, texts):
            with self._lock:
                self.calls += len(texts)
            time.sleep(0.25)        # 把窗口拉宽，让并发请求真的撞在一起

            class Result:
                vectors = [[0.1, 0.2, 0.3, 0.4] for _ in texts]
                usage = {"total_tokens": 1}
            return Result()

    provider = Provider()
    retriever = object.__new__(EmbeddingRetriever)
    retriever.provider = provider
    retriever._query_cache = {}
    retriever._cache_order = []
    retriever._cache_lock = threading.Lock()
    retriever._inflight = {}
    retriever._errors = collections.deque(maxlen=20)
    retriever._error_lock = threading.Lock()

    results: list[int] = []

    def hit():
        vec, _usage = retriever._embed_query("同一个问题")
        results.append(len(vec))

    threads = [threading.Thread(target=hit) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    check("10 个并发都拿到了向量", len(results) == 10 and all(n == 4 for n in results), str(results))
    check("只发了一次 embedding（单飞生效）", provider.calls == 1, f"{provider.calls} 次")

    # 错误窗口：成功不该把刚发生的失败抹掉
    retriever._note_error("ConnectionError: boom")
    check("失败被记进窗口", bool(retriever.last_error) and "boom" in retriever.last_error,
          str(retriever.last_error))
    check("窗口内错误计数可见", retriever.recent_errors >= 1, str(retriever.recent_errors))


# ---------------- 18：笔记索引重建与查询并发 ----------------
def test_rebuild_race() -> None:
    print("笔记索引：重建与查询并发不出半份文件")
    tmp = Path(tempfile.mkdtemp(prefix="idx_"))
    entries = [{"id": f"n{i}", "mtime_ns": i, "size": 10} for i in range(40)]

    def docs_provider(entry):
        return f"笔记 {entry['id']} 的正文，包含一些中文内容用于分词。" * 3

    searcher = NoteSearcher(tmp, docs_provider)

    def searching() -> None:
        for _ in range(60):
            searcher.search("正文", entries, semantic="off")

    def rebuilding() -> None:
        for _ in range(6):
            searcher.rebuild(entries, want_vec=False)

    threads = [threading.Thread(target=searching), threading.Thread(target=rebuilding),
               threading.Thread(target=rebuilding)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)

    index_path = searcher.path
    check("索引文件存在", index_path.exists(), str(index_path))
    bad_lines = 0
    rows = 0
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows += 1
            try:
                json.loads(line)
            except json.JSONDecodeError:
                bad_lines += 1
    check("没有半行 JSON", bad_lines == 0, f"{bad_lines} 行坏")
    check("行数与笔记数一致", rows == len(entries), f"{rows} 行 / {len(entries)} 篇")
    leftover = list(tmp.glob(".idx-*.tmp"))
    check("没有残留临时文件", not leftover, str([p.name for p in leftover]))


def main() -> int:
    test_cost_off_lock()
    test_index_snapshot()
    test_single_flight()
    test_rebuild_race()
    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("RUNTIME CONCURRENCY OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
