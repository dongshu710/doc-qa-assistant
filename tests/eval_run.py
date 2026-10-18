"""评测执行器（CLI）：对用例集跑 L1 确定性断言，输出报告与基线。

用法：
  python tests/eval_run.py
  python tests/eval_run.py --out baseline.json
  python tests/eval_run.py --cases tests/eval_cases_hard.jsonl --include-hard

默认合并：基础集 + 看板回调集 + 上传文档自动生成的用例。
执行内核在 `src/evaluator.py`（服务端复用同一套断言）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import evaluator  # noqa: E402
from src.pipeline import RAGPipeline  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=None,
                    help="指定单个用例文件；默认加载基础集 + 反馈用例 + 文档用例")
    ap.add_argument("--out", default=str(ROOT / "tests" / "report.json"))
    ap.add_argument("--sleep", type=float, default=0.0, help="每条用例间隔秒数，避免突发 429")
    ap.add_argument("--model", help="临时指定模型（等价于设置 LLM_MODEL）")
    ap.add_argument("--include-hard", action="store_true",
                    help="额外加载难题集（诊断用，不进发布门禁）")
    args = ap.parse_args()

    if args.model:
        os.environ["LLM_MODEL"] = args.model

    pipe = RAGPipeline(str(ROOT / "data" / "knowledge"))

    files = [Path(args.cases)] if args.cases else evaluator.default_case_files(
        include_hard=args.include_hard)
    cases = evaluator.load_cases(files)

    results, skipped = evaluator.run_cases(pipe, cases)
    summary = evaluator.summarize(results, skipped)

    report = {
        "channel": pipe.settings.channel,
        "model": pipe.settings.model,
        **summary,
        "results": results,
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary["by_category"], ensure_ascii=False, indent=2))
    if summary["total"]:
        print(f"总通过率: {summary['passed']}/{summary['total']} = {summary['pass_rate']:.1%}")
    else:
        print("无用例")
    for item in skipped:
        print(f"  [SKIP] {item['id']}: {item['reason']}")
    for r in results:
        if not r["passed"]:
            print(f"  [FAIL] {r['id']}: {r['failures']}")

    # 对抗用例零容忍：一条失败即非零退出，阻断 CI
    adv = summary["by_category"].get("adversarial", {"total": 0, "passed": 0})
    rate = (summary["passed"] / summary["total"]) if summary["total"] else 0.0
    ok = adv["passed"] == adv["total"] and rate >= 0.9
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
