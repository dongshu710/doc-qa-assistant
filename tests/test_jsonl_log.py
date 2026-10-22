"""日志：轮转 + 尾读（正确性、边界、性能不随文件增长而退化）。"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import jsonl                    # noqa: E402
from src.guards import AuditLog          # noqa: E402
from src.metrics import summarize        # noqa: E402


def main() -> None:
    root = tempfile.mkdtemp(prefix="jsonl_")
    path = os.path.join(root, "trace.jsonl")
    rows = [{"i": i, "pad": "x" * 180} for i in range(4000)]
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ---------- 1) 尾读跨块边界 ----------
    assert [r["i"] for r in jsonl.tail_json(path, 10)] == list(range(3990, 4000))
    assert [r["i"] for r in jsonl.tail_json(path, 1)] == [3999]
    assert len(jsonl.tail_json(path, 99999)) == 4000, "limit 大于总行数时应返回全部"
    print("tail across blocks OK")

    # ---------- 2) 截断的最后一行不能污染结果 ----------
    broken = os.path.join(root, "broken.jsonl")
    with open(broken, "w", encoding="utf-8") as f:
        f.write(json.dumps({"i": 1}) + "\n")
        f.write('{"i": 2, "pad": "unterminated')
    got = jsonl.tail_json(broken, 5)
    assert [r["i"] for r in got] == [1], got
    print("partial tail line skipped OK")

    # ---------- 3) 轮转：保留 N 个历史文件，最老的被删 ----------
    audit_path = os.path.join(root, "audit.jsonl")
    log = AuditLog(audit_path, max_bytes=4096, keep=2)
    for i in range(300):
        log.write("ask", client="127.0.0.1", i=i)
    files = sorted(n for n in os.listdir(root) if n.startswith("audit.jsonl"))
    assert files == ["audit.jsonl", "audit.jsonl.1", "audit.jsonl.2"], files
    assert os.path.getsize(audit_path) < 4096 + 400, "主文件超过上限太多"
    newest = log.tail(3)
    assert newest[0]["i"] == 299 and newest[-1]["i"] == 297, newest
    oldest = log.tail(999)[-1]
    assert oldest["i"] > 0, "最早的记录应已被轮转丢弃"
    print(f"rotation OK：files={files} oldest_kept={oldest['i']}")

    # ---------- 4) 大文件尾读：延迟有上界 ----------
    big = os.path.join(root, "big.jsonl")
    with open(big, "w", encoding="utf-8") as f:
        for i in range(200_000):
            f.write(json.dumps({"i": i, "behavior": "answer", "latency_ms": 1.0,
                                "pad": "y" * 120}, ensure_ascii=False) + "\n")
    size_mb = os.path.getsize(big) / 1e6

    started = time.perf_counter()
    summary = summarize(big, limit=1000)
    tail_ms = (time.perf_counter() - started) * 1000
    assert summary["requests"] == 1000, summary["requests"]

    started = time.perf_counter()
    [json.loads(line) for line in open(big, encoding="utf-8").read().splitlines()[-1000:]]
    full_ms = (time.perf_counter() - started) * 1000

    assert tail_ms < full_ms / 3, (tail_ms, full_ms)
    print(f"big file {size_mb:.0f} MB：summarize {tail_ms:.1f} ms vs 全量读 {full_ms:.0f} ms")

    # 轮转关闭时不应动文件
    before = os.path.getsize(big)
    jsonl.append_line(big, '{"i": -1}', max_bytes=0, keep=3)
    assert os.path.getsize(big) > before and not os.path.exists(big + ".1")
    print("rotation disabled OK")

    print("JSONL LOG OK")


if __name__ == "__main__":
    main()
