"""召回评测：Recall@1 / Recall@4 / MRR，对比不同检索策略。

为什么单独测召回：L1 判「答案对不对」，但答案错可能是**检索没找到**。
H10 就是典型：条款没被召回，模型只能答「资料中未找到」，L3 还给它满分。
把召回单独量化，才能判断该改检索还是改生成。

对比策略：
- bm25              纯词法（原基线）
- hybrid            BM25 + 字符 n-gram 哈希向量，RRF 融合 + 轻量重排
- bm25+expand       BM25 + LLM 查询扩展（语料自适应）
- hybrid+expand     两者叠加（项目默认）

用法：
  python tests/eval_retrieval.py                       # 离线跑 bm25 / hybrid
  python tests/eval_retrieval.py --expand --sleep 1    # 加上查询扩展（需 Key）
"""
import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.chunking import load_corpus  # noqa: E402
from src.pipeline import _build_vocabulary  # noqa: E402
from src.query import expand  # noqa: E402
from src.retriever import build_retriever  # noqa: E402


def _norm(text: str) -> str:
    return "".join((text or "").split())


def _satisfied(labels: list[str], mode: str, texts: list[str]) -> bool:
    if not labels:
        return True
    blob = _norm(" ".join(texts))
    hits = [_norm(lb) in blob for lb in labels]
    return all(hits) if mode == "all" else any(hits)


def _first_hit_rank(labels: list[str], mode: str, chunks) -> int | None:
    """第一个满足条件的片段名次（1 起）；all 模式要求累计满足。"""
    seen: list[str] = []
    for rank, c in enumerate(chunks, 1):
        seen.append(c.section + " " + c.text)
        if _satisfied(labels, mode, seen):
            return rank
    return None


def evaluate(cases, retriever, ks, expand_vocab=None, sleep_s: float = 0.0) -> dict:
    detail = []
    for idx, case in enumerate(cases):
        expect = case.get("expect", {})
        labels = expect.get("retrieval_contains") or expect.get("retrieval_contains_any") or []
        mode = "all" if expect.get("retrieval_contains") else "any"
        if not labels:
            continue
        query = case["input"]
        applied = False
        if expand_vocab is not None:
            if idx and sleep_s > 0:
                time.sleep(sleep_s)
            query, applied = expand(case["input"], expand_vocab)

        hits = retriever.search(query, max(ks), focus_query=case["input"])
        chunks = [c for c, _s in hits]
        ranks = {}
        for k in ks:
            ranks[str(k)] = _satisfied(labels, mode, [c.section + " " + c.text for c in chunks[:k]])
        detail.append({
            "id": case["id"],
            "query": case["input"],
            "search_query": query if applied else None,
            "labels": labels,
            "mode": mode,
            "hit_at": ranks,
            "first_hit_rank": _first_hit_rank(labels, mode, chunks),
            "top": [f"{c.title}·{c.section}" for c in chunks],
        })

    out = {"cases": len(detail)}
    for k in ks:
        out[f"recall_at_{k}"] = round(
            sum(1 for d in detail if d["hit_at"][str(k)]) / len(detail), 3
        ) if detail else None
    rr = [1.0 / d["first_hit_rank"] for d in detail if d["first_hit_rank"]]
    out["mrr"] = round(statistics.mean(rr), 3) if rr else 0.0
    out["misses"] = [d["id"] for d in detail if not d["hit_at"][str(max(ks))]]
    out["detail"] = detail
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="召回评测（Recall@k / MRR）")
    ap.add_argument("--cases", default=str(ROOT / "tests" / "eval_cases_hard.jsonl"))
    ap.add_argument("--knowledge", default=str(ROOT / "data" / "knowledge"))
    ap.add_argument("--ks", default="1,4")
    ap.add_argument("--expand", action="store_true", help="加入 LLM 查询扩展（需 API Key）")
    ap.add_argument("--sleep", type=float, default=1.0, help="扩展时每条间隔秒数")
    ap.add_argument("--out", default=str(ROOT / "tests" / "report_retrieval.json"))
    args = ap.parse_args()

    ks = [int(x) for x in args.ks.split(",") if x.strip()]
    cases = [json.loads(l) for l in Path(args.cases).read_text(encoding="utf-8").splitlines() if l.strip()]
    chunks = load_corpus(args.knowledge)
    vocab = _build_vocabulary(chunks) if args.expand else None

    configs = {}
    for mode in ("bm25", "hybrid"):
        retriever = build_retriever(chunks, mode)
        configs[mode] = evaluate(cases, retriever, ks)
        if vocab is not None:
            configs[f"{mode}+expand"] = evaluate(cases, retriever, ks, expand_vocab=vocab, sleep_s=args.sleep)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases_file": str(args.cases),
        "chunks": len(chunks),
        "ks": ks,
        "with_expansion": bool(args.expand),
        "configs": configs,
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{'策略':<16}{'R@' + str(ks[0]):>8}{'R@' + str(ks[-1]):>8}{'MRR':>8}   未命中")
    for name, res in configs.items():
        print(f"{name:<16}{res[f'recall_at_{ks[0]}']:>8.1%}{res[f'recall_at_{ks[-1]}']:>8.1%}"
              f"{res['mrr']:>8.3f}   {','.join(res['misses']) or '-'}")
    print(f"\n报告：{args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
