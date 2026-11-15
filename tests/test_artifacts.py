"""运行时产物落点：迁移、不覆盖、回退读。

守的是三件事，每一件都在真实场景里会静默出错：
1. 升级后第一次启动，旧 `tests/` 里的反馈用例要搬到数据目录（不能丢）；
2. 搬过一次就绝不覆盖——用户后来攒的用例比旧文件值钱；
3. 没有组合根的上下文（CLI、单测）仍能读到旧位置，不会突然显示 0 条。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import artifacts  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def test_migrate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "proj"
        home = Path(tmp) / "notes"
        (project / "tests").mkdir(parents=True)
        legacy = project / "tests" / "eval_cases_feedback.jsonl"
        legacy.write_text('{"id":"F001"}\n', encoding="utf-8")

        os.environ.pop("ARTIFACTS_DIR", None)
        paths = artifacts.resolve(str(project), str(home))
        target = Path(paths["eval_cases_feedback.jsonl"])
        check("迁移到 <存储区>/artifacts", target == home / "artifacts" / "eval_cases_feedback.jsonl",
              str(target))
        check("内容搬过去了", target.exists() and target.read_text(encoding="utf-8") == '{"id":"F001"}\n')
        check("旧文件保留（可核对后自删）", legacy.exists())

        # 用户后来在数据目录里攒了新的：再次启动不能覆盖
        target.write_text('{"id":"F002"}\n', encoding="utf-8")
        artifacts.resolve(str(project), str(home))
        check("已有新数据不被覆盖", target.read_text(encoding="utf-8") == '{"id":"F002"}\n')


def test_env_override() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "proj"
        (project / "tests").mkdir(parents=True)
        custom = Path(tmp) / "custom"
        os.environ["ARTIFACTS_DIR"] = str(custom)
        try:
            paths = artifacts.resolve(str(project), str(Path(tmp) / "notes"))
            check("ARTIFACTS_DIR 优先", Path(paths["report_doc_cases.json"]).parent == custom,
                  paths["report_doc_cases.json"])
        finally:
            os.environ.pop("ARTIFACTS_DIR", None)


def test_read_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "proj"
        (project / "tests").mkdir(parents=True)
        legacy = project / "tests" / "eval_cases_docs.jsonl"
        legacy.write_text("x\n", encoding="utf-8")

        artifacts.activate({})
        check("未登记时回退旧位置", artifacts.read_path("eval_cases_docs.jsonl", str(project)) == str(legacy))

        target = str(Path(tmp) / "notes" / "artifacts" / "eval_cases_docs.jsonl")
        artifacts.activate({"eval_cases_docs.jsonl": target})
        check("登记后走新位置", artifacts.read_path("eval_cases_docs.jsonl", str(project)) == target)
        artifacts.activate({})   # 还原，避免影响同进程里的其他用例


def test_evaluator_follows() -> None:
    """评测器必须读同一个落点，否则「页面上存了用例、跑评测时不存在」。"""
    from src import evaluator

    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "proj"
        (project / "tests").mkdir(parents=True)
        target = Path(tmp) / "artifacts" / "eval_cases_feedback.jsonl"
        target.parent.mkdir(parents=True)
        target.write_text('{"id":"F009"}\n', encoding="utf-8")
        artifacts.activate({"eval_cases_feedback.jsonl": str(target)})
        try:
            check("evaluator 读到数据目录的反馈用例", evaluator.feedback_path() == target,
                  str(evaluator.feedback_path()))
            check("默认用例集包含它",
                  target in [Path(p) for p in evaluator.default_case_files(include_docs=False)])
        finally:
            artifacts.activate({})


def main() -> int:
    test_migrate()
    test_env_override()
    test_read_fallback()
    test_evaluator_follows()
    if FAILED:
        print(f"\nARTIFACTS TESTS FAILED：{len(FAILED)} 项")
        return 1
    print("\nARTIFACTS TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
