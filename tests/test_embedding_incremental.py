"""embedding 增量重建：改一篇文档只重嵌变了的块，缓存有上限。

这条差距在原报告里写的是「改一篇文档要全量重嵌」。实测发现**不成立**：
`EmbeddingCache` 本来就是按内容哈希缓存的，改 1 块只嵌 1 块。
但这个结论必须被测试钉住——它依赖三个容易在重构中被破坏的前提：
缓存键包含 model 与 dim、`get_many` 命中后仍按原顺序返回、`build()` 真的用了缓存。

真正的缺陷是另外两条，这里一起测：
- 缓存无上限：每改一次条款就留一份旧向量，几个月后全是死数据；
- 重建成本不可见：`embedded=0` 与「没生效」在界面上长得一样。
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.embeddings import EmbeddingCache  # noqa: E402
from src.vector_store import EmbeddingIndex  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


class CountingProvider:
    """记账用的假 provider：只关心「这次嵌了几条」。"""

    def __init__(self, dim: int = 8) -> None:
        self.model = "fake-count"
        self.dim = dim
        self.embedded = 0

    def embed(self, texts):
        self.embedded += len(texts)
        return SimpleNamespace(
            vectors=[[float(len(text) % 7) + 1.0] * self.dim for text in texts],
            dim=self.dim,
            usage={"prompt_tokens": 0, "completion_tokens": 0,
                   "total_tokens": len(texts)})


def corpus(count: int = 60, tweak: int | None = None):
    rows = []
    for index in range(count):
        text = f"第{index}条 稳盈系列产品的条款内容"
        if tweak == index:
            text += "（修订）"
        rows.append(SimpleNamespace(doc_id=f"doc{index // 20}", title="产品要素",
                                    section="条款", text=text, chunk_index=index))
    return rows


def test_incremental(tmp: str) -> None:
    print("增量：只有变更的块重新嵌")
    provider = CountingProvider()
    index = EmbeddingIndex(corpus(), provider, tmp, store_kind="flat")
    index.build()
    first = provider.embedded
    check("首次建库嵌入全部块", first == 60, str(first))
    check("首次 reused 为 0", index.build_usage.get("reused") == 0,
          str(index.build_usage))

    provider.embedded = 0
    again = EmbeddingIndex(corpus(), provider, tmp, store_kind="flat")
    again.build()
    check("语料没变：一条都不重嵌", provider.embedded == 0, str(provider.embedded))
    check("reused 等于全量块数", again.build_usage.get("reused") == 60,
          str(again.build_usage))

    provider.embedded = 0
    changed = EmbeddingIndex(corpus(tweak=7), provider, tmp, store_kind="flat")
    changed.build()
    check("改 1 块：只嵌 1 块", provider.embedded == 1, str(provider.embedded))
    check("embedded + reused == 总块数",
          changed.build_usage.get("embedded", 0) + changed.build_usage.get("reused", 0) == 60,
          str(changed.build_usage))

    provider.embedded = 0
    index2 = EmbeddingIndex(corpus(), provider, tmp, store_kind="flat")
    index2.build()
    check("回滚到旧内容：命中旧缓存，不重嵌", provider.embedded == 0,
          str(provider.embedded))

    provider2 = CountingProvider(dim=8)
    provider2.model = "another-model"
    other = EmbeddingIndex(corpus(), provider2, tmp, store_kind="flat")
    other.build()
    check("换模型必须全部重嵌（缓存键含模型名）", provider2.embedded == 60,
          str(provider2.embedded))


def test_cache_bound(tmp: str) -> None:
    print("缓存上限：超限淘汰最久未命中的")
    path = os.path.join(tmp, "cache.jsonl")
    cache = EmbeddingCache(path, "m", 8, max_entries=1000)
    texts = [f"块 {i}" for i in range(1200)]
    cache.put_many(texts[:1200], [[1.0] * 8 for _ in range(1200)])
    check("超出上限后条目被压到上限", cache.stats()["entries"] == 1000,
          str(cache.stats()))
    cache.save()

    reloaded = EmbeddingCache(path, "m", 8, max_entries=1000)
    check("落盘文件也遵守上限", reloaded.stats()["entries"] == 1000,
          str(reloaded.stats()))
    _vectors, missing = reloaded.get_many(texts)
    check("最早写入的被淘汰（前 200 条要重嵌）", len(missing) == 200, str(len(missing)))
    check("最近写入的还在", 1199 not in missing, "最后一条不该被淘汰")

    hits = reloaded.get_many(texts[1000:])[1]
    check("命中计数累加", reloaded.stats()["hits"] >= 200 and not hits,
          str(reloaded.stats()))

    # 上限的下限保护：配成 1 会把缓存压到不可用，必须退回安全值
    tiny = EmbeddingCache(os.path.join(tmp, "t.jsonl"), "m", 8, max_entries=1)
    check("过小的上限被抬到 1000", tiny.max_entries == 1000, str(tiny.max_entries))
    os.environ["EMBEDDING_CACHE_MAX"] = "abc"
    bad = EmbeddingCache(os.path.join(tmp, "b.jsonl"), "m", 8)
    check("坏配置退回默认而不是崩", bad.max_entries == 20000, str(bad.max_entries))
    os.environ.pop("EMBEDDING_CACHE_MAX", None)


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="embinc_")
    test_incremental(tmp)
    test_cache_bound(tmp)
    if FAILED:
        print(f"\nEMBEDDING INCREMENTAL: {FAILED} FAILED")
        raise SystemExit(1)
    print("\nEMBEDDING INCREMENTAL OK")


if __name__ == "__main__":
    main()
