"""评测执行内核：加载用例、跑 L1 断言、汇总。

放在 `src/` 而不是 `tests/`，是因为服务端也要用（看板「运行用例」按钮），
`tests/eval_run.py` 只是它的一层 CLI 包装——避免同一套断言逻辑写两遍。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "tests" / "eval_cases.jsonl"
FEEDBACK = ROOT / "tests" / "eval_cases_feedback.jsonl"
DOCS = ROOT / "tests" / "eval_cases_docs.jsonl"
HARD = ROOT / "tests" / "eval_cases_hard.jsonl"


def _norm(text: str) -> str:
    """断言前去掉所有空白：中文金额/单位间空格与否不应影响事实判定。"""
    return re.sub(r"\s+", "", text or "")


def check_l1(case: dict, actual: dict, context: list[dict] | None = None) -> list[str]:
    """确定性断言。返回失败原因列表，空列表表示通过。

    `retrieval_contains*` 检查「该题所需的条款是否被召回」——这是 L3 看不见的盲区：
    裁判只看检索到的资料，条款没召回时「未找到」对裁判反而是忠实的，会给满分。
    """
    failures: list[str] = []
    expect = case.get("expect", {})

    if "behavior" in expect and actual.get("behavior") != expect["behavior"]:
        failures.append(f"行为不符: 期望 {expect['behavior']}, 实际 {actual.get('behavior')}")

    answer_n = _norm(actual.get("answer", ""))

    for kw in expect.get("output_contains", []):
        if _norm(kw) not in answer_n:
            failures.append(f"输出缺少关键内容: {kw}")

    any_kw = expect.get("output_contains_any", [])
    if any_kw and not any(_norm(kw) in answer_n for kw in any_kw):
        failures.append(f"输出未命中任一关键词: {any_kw}")

    for kw in expect.get("must_not_leak", []):
        if _norm(kw).lower() in answer_n.lower():
            failures.append(f"泄露了禁止内容: {kw}")

    if "max_steps" in expect and actual.get("steps", 0) > expect["max_steps"]:
        failures.append(f"步数超限: {actual.get('steps')} > {expect['max_steps']}")

    ctx = _norm("".join(str(c.get("text", "")) for c in (context or [])))
    if ctx:
        for kw in expect.get("retrieval_contains", []):
            if _norm(kw) not in ctx:
                failures.append(f"检索未召回关键条款: {kw}")
        any_hit = expect.get("retrieval_contains_any", [])
        if any_hit and not any(_norm(kw) in ctx for kw in any_hit):
            failures.append(f"检索未召回关键条款（任一）: {any_hit}")

    return failures


def default_case_files(include_hard: bool = False, include_docs: bool = True) -> list[Path]:
    files = [CURATED]
    if FEEDBACK.exists():
        files.append(FEEDBACK)
    if include_docs and DOCS.exists():
        files.append(DOCS)
    if include_hard:
        files.append(HARD)
    return files


def load_cases(files: list[Path]) -> list[dict]:
    """加载并去重（按 id）。文件不存在就跳过，不让缺文件把评测拦死。"""
    cases, seen = [], set()
    for fp in files:
        fp = Path(fp)
        if not fp.exists():
            continue
        for line in fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError:
                continue
            if case.get("id") in seen:
                continue
            seen.add(case.get("id"))
            cases.append(case)
    return cases


def run_cases(pipe, cases: list[dict], sleep: float = 0.0,
              skip_missing_doc: bool = False, kb_dir: str | Path | None = None) -> tuple[list[dict], list[dict]]:
    """逐条执行。返回 (results, skipped)。

    `skip_missing_doc=True` 时，若用例对应的上传文档已被删除，就跳过并说明原因——
    静默失败比报错更难查。
    """
    results: list[dict] = []
    skipped: list[dict] = []
    kb = Path(kb_dir) if kb_dir else None

    for idx, case in enumerate(cases):
        doc_id = case.get("doc_id")
        if skip_missing_doc and doc_id and kb is not None:
            if not (kb / f"{doc_id}.md").exists():
                skipped.append({"id": case.get("id"), "reason": f"文档 {doc_id}.md 已不在知识库"})
                continue
        if idx and sleep > 0:
            time.sleep(sleep)

        actual = pipe.ask(case["input"])

        # 供 L3 裁判与召回断言使用：记录当时检索到的资料原文（BM25 确定性，可复现）
        try:
            sq = actual.get("search_query") or case["input"]
            hits = pipe.retriever.search(sq, pipe.settings.top_k, focus_query=case["input"])
        except Exception:  # noqa: BLE001 —— 仅用于取证，失败不影响判定
            hits = []
        context = [
            {"ref": i, "title": c.title, "section": c.section, "text": c.text[:400]}
            for i, (c, _s) in enumerate(hits, 1)
        ]

        failures = check_l1(case, actual, context)
        results.append({
            "id": case["id"],
            "category": case.get("category", "unknown"),
            "input": case["input"],
            "expect": case.get("expect", {}),
            "source": case.get("source"),
            "doc_id": doc_id,
            "passed": not failures,
            "failures": failures,
            "behavior": actual.get("behavior"),
            "mode": actual.get("mode"),
            "answer": actual.get("answer", "")[:800],
            "citations": actual.get("citations", []),
            "citation_coverage": actual.get("citation_coverage"),
            "degraded": actual.get("degraded"),
            "degrade_reason": actual.get("degrade_reason"),
            "context": context,
            "latency_ms": actual.get("latency_ms"),
        })
    return results, skipped


def summarize(results: list[dict], skipped: list[dict] | None = None) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    by_cat: dict[str, dict] = {}
    for cat in sorted({r["category"] for r in results}):
        subset = [r for r in results if r["category"] == cat]
        by_cat[cat] = {"total": len(subset), "passed": sum(1 for r in subset if r["passed"])}
    return {
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "by_category": by_cat,
        "skipped": skipped or [],
    }
