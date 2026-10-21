"""关键词匹配性能对照：倒排索引 vs 逐条包含判断。

跑法：
    python tests/bench_keyword.py
    python tests/bench_keyword.py --entries 20000 --queries 500

只测匹配这一段（不含抽取与建索引），因为它是每次提问都要走的热路径。
合成条目用金融常见词根拼装，长度分布接近真实标签。
"""
import argparse
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_settings  # noqa: E402
from src.keywords import DIRECT_KINDS, Entry, KeywordIndex, _norm  # noqa: E402

ROOTS = ["起购", "赎回", "风险", "期限", "费率", "额度", "评级", "冷静期", "双录",
         "披露", "存单", "定存", "净值", "收益", "转让"]


def build(entries: int) -> list[Entry]:
    out: list[Entry] = []
    i = 0
    while len(out) < entries:
        term = "".join(ROOTS[(i // (len(ROOTS) ** k)) % len(ROOTS)] for k in range(4))
        out.append(Entry(term=term, doc_id=f"d{i % 80}", title="t", section="s",
                         snippet=f"{term}：示例原文 {i}", kind="colon", weight=0.9,
                         chunk_index=i))
        i += 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entries", type=int, default=6750)
    parser.add_argument("--queries", type=int, default=300)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    random.seed(args.seed)
    rows = build(args.entries)
    index = KeywordIndex([], load_settings())
    index.entries = rows
    index._build_key_index()

    queries = []
    for i in range(args.queries):
        if i % 2 == 0:  # 一半真的命中一条，走完整的打分与去重路径
            queries.append(random.choice(rows).term + "是多少")
        else:
            queries.append("".join(random.choice(ROOTS) for _ in range(4)))

    def linear(query: str) -> list[Entry]:
        q = _norm(query)
        found = []
        for entry in rows:
            if entry.kind not in DIRECT_KINDS:
                continue
            if any(len(k) >= 2 and k in q for k in entry.keys()):
                found.append(entry)
        return found

    t0 = time.perf_counter()
    for query in queries:
        index.match_report(query)
    inverted = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    for query in queries:
        linear(query)
    linear_ms = (time.perf_counter() - t0) * 1000

    print(f"条目 {len(rows)} · 查询 {len(queries)}")
    print(f"倒排索引 {inverted:.1f} ms（{inverted / len(queries):.3f} ms/次）")
    print(f"线性扫描 {linear_ms:.1f} ms（{linear_ms / len(queries):.3f} ms/次）")
    print(f"提速 {linear_ms / inverted:.1f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
