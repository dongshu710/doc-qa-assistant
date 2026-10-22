"""汇报页数据缓存：静态输入不变时命中，评测报告或知识库一变就失效。

缓存键用 mtime/size 而不是时间：上传/审批/评测跑完都会改文件，
按时间缓存会出现「刚跑完评测，汇报页还是旧数字」。
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_KEYS = ("LLM_API_KEY", "DEEPSEEK_API_KEY")


def _baseline(pass_rate: float) -> dict:
    return {
        "total": 2, "pass_rate": pass_rate, "channel": "offline", "model": "extractive",
        "by_category": {"要素": {"passed": 1, "total": 2}},
        "results": [{"passed": True, "question": "q1"}, {"passed": False, "question": "q2"}],
    }


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="report_cache_"))
    kb = tmp / "kb"
    kb.mkdir()
    (kb / "a.md").write_text("# 甲\n\n## 要素\n\n起购金额 1000 元。\n", encoding="utf-8")
    (kb / "b.md").write_text("# 乙\n\n## 要素\n\n风险等级 R2。\n", encoding="utf-8")

    tests = tmp / "tests"
    tests.mkdir()
    (tests / "eval_cases.jsonl").write_text('{"question":"q1"}\n', encoding="utf-8")
    (tests / "baseline.json").write_text(json.dumps(_baseline(0.5)), encoding="utf-8")

    env = {"KEYWORD_INDEX": str(tmp / "keywords.json"), "RETRIEVAL": "bm25",
           "QUERY_EXPANSION": "off", "REPORT_CACHE_TTL": "60"}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    for key in _KEYS:
        os.environ.pop(key, None)

    from src.pipeline import RAGPipeline
    from src.report import cache_stats, collect

    pipe = RAGPipeline(str(kb))
    try:
        t0 = time.perf_counter()
        cold = collect(pipe, root=tmp)
        t1 = time.perf_counter()
        warm = collect(pipe, root=tmp)
        t2 = time.perf_counter()
        assert cold["cache"]["hit"] is False, cold["cache"]
        assert warm["cache"]["hit"] is True, warm["cache"]
        assert warm["generated_at"] == cold["generated_at"]
        assert warm["knowledge"]["chunks"] == cold["knowledge"]["chunks"]
        print(f"命中 OK：冷 {1000 * (t1 - t0):.1f}ms → 热 {1000 * (t2 - t1):.2f}ms")

        # ---------- 评测报告变了 → 失效 ----------
        time.sleep(0.01)
        (tests / "baseline.json").write_text(json.dumps(_baseline(1.0)), encoding="utf-8")
        after_report = collect(pipe, root=tmp)
        assert after_report["cache"]["hit"] is False, after_report["cache"]
        assert abs(after_report["l1"][0]["pass_rate"] - 1.0) < 1e-9, after_report["l1"]
        print("评测报告 mtime 变化 → 缓存失效 OK")

        # ---------- 知识库文件变了 → 失效 ----------
        time.sleep(0.01)
        (kb / "a.md").write_text("# 甲\n\n## 要素\n\n起购金额 2000 元。\n", encoding="utf-8")
        after_kb = collect(pipe, root=tmp)
        assert after_kb["cache"]["hit"] is False, after_kb["cache"]
        print("知识库变更 → 缓存失效 OK")

        # ---------- TTL=0 关闭缓存 ----------
        os.environ["REPORT_CACHE_TTL"] = "0"
        a = collect(pipe, root=tmp)
        b = collect(pipe, root=tmp)
        assert a["cache"]["hit"] is False and b["cache"]["hit"] is False, (a["cache"], b["cache"])
        assert a["cache"]["ttl_s"] == 0
        print("TTL=0 关闭缓存 OK")

        stats = cache_stats()
        assert stats["hit"] >= 1 and stats["miss"] >= 3, stats
        print(f"缓存统计 OK：hit={stats['hit']} miss={stats['miss']} entries={stats['entries']}")
        print("REPORT CACHE TESTS PASSED")
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    main()
