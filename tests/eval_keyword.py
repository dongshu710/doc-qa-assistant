"""关键词直出评测：带标注的命中集 / 不应直出集，输出可复核的指标。

跑法：
    python tests/eval_keyword.py
    python tests/eval_keyword.py --json tests/report_keyword.json

指标口径：
- `direct_hit@1`：应直出的问题里，第一条命中是否落在标注的条目上（看原文片段）；
- `no_direct_fp`：不应直出的问题里，有多少被误直出（越低越好）；
- `gate`：被解释型意图闸门挡下的数量，用来判断规则是救火还是误伤。
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.chunking import load_corpus  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.keywords import KeywordIndex  # noqa: E402

DEMO = ROOT / "data" / "demo"
KNOWLEDGE = ROOT / "data" / "knowledge"

# (问题, 期望命中的原文标签；None 表示不应直出)
DIRECT_CASES = [
    ("我爱吃什么", "爱吃的食物"),
    ("我不吃什么", "不吃的食物"),
    ("我有什么忌口", "忌口"),
    ("我几点起床", "起床时间"),
    ("我几点睡觉", "睡觉时间"),
    ("我养了什么宠物", "宠物"),
    ("我有什么爱好", "爱好"),
    ("我的早餐是什么", "早餐"),
    ("我喜欢什么音乐", "喜欢的音乐"),
    ("我讨厌什么天气", "讨厌的天气"),
    ("我不吃香菜", "不吃的食物"),
    ("我不喜欢的运动是什么", "不喜欢的运动"),
    ("我常去的书店是哪家", "常去的书店"),
]

NO_DIRECT_CASES = [
    ("今天天气怎么样", "demo"),
    ("帮我订一张机票", "demo"),
    ("什么是净值型理财", "demo"),
    ("我为什么不能吃香菜", "demo"),
    ("我该怎么安排运动", "demo"),
    ("稳盈系列的起购金额是多少", "finance"),
    ("大额存单可以转让吗", "finance"),
    ("理财产品风险等级分为几档", "finance"),
    ("R3 及以上产品首次购买有什么要求", "finance"),
]

CORPORA = {"demo": DEMO, "finance": KNOWLEDGE}


def build(name: str) -> KeywordIndex:
    os.environ["KEYWORD_INDEX"] = os.path.join(tempfile.mkdtemp(prefix="kw_eval_"), "kw.json")
    index = KeywordIndex(load_corpus(str(CORPORA[name])), load_settings())
    index.ensure(enrich=False)
    return index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", help="把指标写到指定文件")
    parser.add_argument("--show", action="store_true", help="打印每条用例的命中详情")
    args = parser.parse_args()

    indexes = {name: build(name) for name in CORPORA}
    demo = indexes["demo"]

    hits, misses, gates = 0, [], 0
    rows = []
    for query, label in DIRECT_CASES:
        report = demo.match_report(query)
        if report.gate:
            gates += 1
        first = report.hits[0] if report.hits else None
        ok = bool(first and label in first.entry.snippet)
        hits += 1 if ok else 0
        rows.append({"query": query, "expect": label, "ok": ok,
                     "got": first.entry.term if first else None,
                     "gate": report.gate,
                     "rejected": [r["reason"] for r in report.rejected]})
        if not ok:
            misses.append((query, label, first.entry.term if first else None))

    fp, fp_rows = 0, []
    for query, corpus in NO_DIRECT_CASES:
        report = indexes[corpus].match_report(query)
        if report.gate:
            gates += 1
        if report.hits:
            fp += 1
            fp_rows.append((query, corpus, report.hits[0].entry.term))

    total = len(DIRECT_CASES)
    metrics = {
        "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "direct_cases": total,
        "direct_hit": hits,
        "direct_hit_rate": round(hits / total, 3) if total else 0.0,
        "no_direct_cases": len(NO_DIRECT_CASES),
        "no_direct_fp": fp,
        "no_direct_fp_rate": round(fp / len(NO_DIRECT_CASES), 3) if NO_DIRECT_CASES else 0.0,
        "gate_blocked": gates,
        "entries": len(demo.entries),
        "direct_entries": sum(1 for e in demo.entries if e.kind in ("item", "colon", "explicit", "llm")),
    }

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if misses:
        print("\n未命中：")
        for query, label, got in misses:
            print(f"  {query}  期望={label}  实际={got}")
    if fp_rows:
        print("\n误直出：")
        for query, corpus, term in fp_rows:
            print(f"  [{corpus}] {query} -> {term}")
    if args.show:
        print("\n明细：")
        for row in rows:
            flag = "OK " if row["ok"] else "MISS"
            print(f"  {flag} {row['query']:<24} expect={row['expect']:<10} "
                  f"got={row['got']} rejected={row['rejected']}")

    if args.json:
        Path(args.json).write_text(
            json.dumps({**metrics, "cases": rows}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"\n写入 {args.json}")
    return 0 if not misses and not fp else 1


if __name__ == "__main__":
    raise SystemExit(main())
