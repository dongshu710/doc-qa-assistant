"""从 logs/trace.jsonl 汇总观测指标（P50/P95、降级率、引用覆盖率、token 用量）。

用法：
  python -m src.metrics
  python -m src.metrics --limit 200 --json
"""
import argparse
import json
from pathlib import Path


def _percentile(values: list[float], p: float):
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[k]


def summarize(trace_path: str, limit: int = 1000) -> dict:
    path = Path(trace_path)
    if not path.exists():
        return {"requests": 0, "note": "trace 文件不存在"}
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()][-limit:]
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    n = len(rows)
    behaviors = ("answer", "ask_clarify", "no_answer", "refuse")
    modes = ("llm", "extractive", "extractive_fallback")
    latencies = [r.get("latency_ms", 0.0) for r in rows]
    coverages = [r.get("citation_coverage", 0.0) for r in rows if r.get("behavior") == "answer"]
    tokens = sum((r.get("usage") or {}).get("total_tokens", 0) for r in rows)
    degraded_reasons: dict[str, int] = {}
    for r in rows:
        if r.get("degrade_reason"):
            degraded_reasons[r["degrade_reason"]] = degraded_reasons.get(r["degrade_reason"], 0) + 1

    return {
        "requests": n,
        "by_behavior": {b: sum(1 for r in rows if r.get("behavior") == b) for b in behaviors},
        "by_mode": {m: sum(1 for r in rows if r.get("mode") == m) for m in modes},
        "degraded": sum(1 for r in rows if r.get("degraded")),
        "citation_repaired": sum(1 for r in rows if r.get("citation_repaired")),
        "degrade_reasons": degraded_reasons,
        "avg_citation_coverage": round(sum(coverages) / len(coverages), 3) if coverages else None,
        "latency_ms": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "max": max(latencies) if latencies else None,
        },
        "total_tokens": tokens,
        "by_channel": {
            ch: sum(1 for r in rows if r.get("channel") == ch)
            for ch in sorted({r.get("channel") for r in rows if r.get("channel")})
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="汇总 trace 指标")
    ap.add_argument("--trace", default=str(Path(__file__).resolve().parent.parent / "logs" / "trace.jsonl"))
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = ap.parse_args()
    summary = summarize(args.trace, args.limit)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    print(f"请求数: {summary['requests']}")
    print(f"行为分布: {summary['by_behavior']}")
    print(f"模式分布: {summary['by_mode']}")
    print(f"降级: {summary['degraded']}  原因: {summary['degrade_reasons']}")
    print(f"平均引用覆盖率: {summary['avg_citation_coverage']}")
    print(f"延迟 P50/P95/max: {summary['latency_ms']}")
    print(f"总 token: {summary['total_tokens']}")
    print(f"按通道: {summary['by_channel']}")


if __name__ == "__main__":
    main()
