"""汇报页渲染：字段表与各区块可单独断言。

为什么拆：`render` 原来是 363 行的单一函数，「算数据」和「拼 HTML」缠在一起，
改一处配色要滚三屏。现在每个区块是独立函数，这里锁住三件事——
字段表标签固定、空数据不崩、有数据才出现对应 section。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import report  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def sample() -> dict:
    return {
        "knowledge": {"chunks": 120, "files": [{"name": "a.md", "chunks": 80},
                                               {"name": "b.md", "chunks": 40}]},
        "cases": {"total": 26},
        "metrics": {"avg_citation_coverage": 0.93, "latency_ms": {"p95": 412.6}},
        "l1": [{"label": "baseline", "total": 26, "pass_rate": 1.0,
                "by_category": {"事实": {"passed": 10, "total": 10}}},
               {"label": "v1.2", "total": 26, "pass_rate": 0.85,
                "by_category": {"事实": {"passed": 8, "total": 10}}}],
        "l3": {"avg": {"faithfulness": 4.5, "relevance": 4.25, "completeness": 3.75},
               "gate": {"passed": False, "reasons": ["忠实度低于 4.6"]},
               "calibration": [{"label": "错值", "dim": "faithfulness", "score": 2.0, "caught": True},
                               {"label": "跳过项", "skipped": True}],
               "pass_rate": 0.9, "answer_cases": 20, "safety_cases": 6,
               "hallucinations": [{"x": 1}], "total_tokens": 12000, "judge_model": "judge-x"},
        "hard": {"total": 8, "pass_rate": 0.75, "results": [{"passed": True}, {"passed": False}],
                 "by_category": {"多跳": {"passed": 3, "total": 4}}},
        "l3_hard": {"same": {"avg": {"faithfulness": 4.0}, "pass_rate": 0.7,
                             "hallucinations": [], "judge_model": "same-m"},
                    "cross": {"avg": {"faithfulness": 3.5}, "pass_rate": 0.6,
                              "hallucinations": [{"x": 1}], "judge_model": "other-m"}},
        "retrieval": {"cases": 12, "configs": {
            "vector": {"recall_at_1": 0.75, "recall_at_4": 0.9166, "mrr": 0.8231,
                       "misses": ["同义改写"]},
            "bm25": {"recall_at_1": 0.5, "recall_at_4": 0.8333, "mrr": 0.6412, "misses": []}}},
        "config": {"keyword_top_n": 3, "top_k": 4, "min_score": 0.3, "timeout": 30, "retries": 2},
        "channel": "deepseek", "model": "deepseek-chat", "generated_at": "2026-10-28 19:00",
    }


def test_kpi_table() -> None:
    print("KPI 字段表")
    rows = report.kpi_rows(sample())
    labels = [label for label, _ in rows]
    check("固定 6 行", len(rows) == 6, str(len(rows)))
    check("标签与顺序固定", labels == ["知识库规模", "评测用例", "L1 通过率",
                                       "L3 忠实度", "引用覆盖率", "P95 延迟（近 500 条）"],
          str(labels))
    values = dict(rows)
    check("知识库规模带份数", values["知识库规模"] == "120 块 / 2 份", values["知识库规模"])
    check("L1 取最高的一轮", values["L1 通过率"] == "100%", values["L1 通过率"])
    check("P95 取整带单位", values["P95 延迟（近 500 条）"] == "413ms",
          values["P95 延迟（近 500 条）"])

    empty = sample()
    empty["l1"] = []
    empty["l3"] = None
    empty["metrics"] = {}
    rows = dict(report.kpi_rows(empty))
    check("无 L1 时给占位符", rows["L1 通过率"] == "-", rows["L1 通过率"])
    check("无引用覆盖率时给占位符", rows["引用覆盖率"] == "-", rows["引用覆盖率"])


def test_blocks() -> None:
    print("区块：空数据不崩、有数据出结构")
    check("空 L1 给提示", "尚未生成 L1" in report._block_l1([]))
    check("L1 有数据出表格", "<table>" in report._block_l1(sample()["l1"]))
    check("无 L3 给提示", "尚未运行 L3" in report._block_l3(None))
    check("L3 有数据出门禁", "门禁未过" in report._block_l3(sample()["l3"]))
    check("L3 校准标出跳过", "跳过" in report._block_l3(sample()["l3"]))
    check("无难题集返回空串", report._block_hard({}, {}) == "")
    check("有难题集出现 section", 'id="s-hard"' in report._block_hard(
        sample()["hard"], sample()["l3_hard"]))
    check("无检索对比返回空串", report._block_retrieval({}) == "")
    check("有检索对比出现 section", 'id="s-ret"' in report._block_retrieval(
        sample()["retrieval"]))


def test_render() -> None:
    print("整页渲染")
    full = report.render(sample())
    check("含 KPI 区块", 'id="s-kpi"' in full)
    check("含检索策略区块", 'id="s-ret"' in full)
    check("含难题集区块", 'id="s-hard"' in full)
    check("非 standalone 有下载按钮", "下载独立 HTML" in full)
    check("KPI 值进了页面", "120 块 / 2 份" in full)

    standalone = report.render(sample(), standalone=True)
    check("standalone 去掉下载按钮", "下载独立 HTML" not in standalone)
    check("standalone 仍保留数据", "120 块 / 2 份" in standalone)

    minimal = sample()
    minimal["l1"] = []
    minimal["l3"] = None
    minimal.pop("hard")
    minimal.pop("l3_hard")
    minimal.pop("retrieval")
    page = report.render(minimal)
    check("缺评测数据也能出页", "<!doctype html>" in page)
    check("缺难题集时不出现该区块", 'id="s-hard"' not in page)


def main() -> int:
    test_kpi_table()
    test_blocks()
    test_render()
    print(f"\n{'全部通过' if FAILED == 0 else f'{FAILED} 项失败'}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
