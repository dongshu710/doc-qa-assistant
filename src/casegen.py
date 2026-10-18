"""从已入库文档自动生成评测用例（回归集）。

为什么需要：上传一份新制度后，「它能不能被正确检索并回答」应该由用例守住，
而不是靠人肉点几次问答。生成的用例进 `tests/eval_cases_docs.jsonl`，与基础集、
反馈集一起跑（`tests/eval_run.py` 默认合并）。

两条生成路径：
- `llm`：让模型读一个知识块，产出「用户会怎么问 + 答案必须出现的关键词」；
- `heuristic`：没有 Key 时的兜底——只从**含数值**的段落出题（金额/期限/比例），
  关键词就是那个数值。宁可少生成，也不生成断言不了的题。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import api_key
from .generator import chat

_NUM_UNIT = re.compile(
    r"\d+(?:\.\d+)?\s*(?:亿元|万元|元|%|％|个工作日|工作日|小时|天|个月|年|日|份|倍)")
_UNIT_KIND = [
    (r"亿元|万元|元", "金额"),
    (r"%|％", "比例"),
    (r"个工作日|工作日", "办理时限"),
    (r"小时", "时限"),
    (r"天|个月|年|日", "期限"),
    (r"份|倍", "数量"),
]

_SYSTEM = (
    "你在为检索问答系统出评测题。只依据给定资料，输出严格 JSON，不要任何解释。\n"
    '格式：{"question": "用户会怎么问（自然口语，不要照抄原文）", '
    '"keywords": ["答案里必须出现的 1-3 个关键信息"], '
    '"behavior": "answer"}\n'
    "要求：问题必须能仅凭该资料回答；keywords 必须是资料中真实出现的字/数字，"
    "优先精确数值；不要出是非题。"
)

_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _unit_kind(token: str) -> str:
    for pattern, label in _UNIT_KIND:
        if re.search(pattern, token):
            return label
    return "数值"


def _anchor_tokens(text: str) -> list[str]:
    """从段落里挑可断言的事实锚点（数值 + 单位）。"""
    seen, out = set(), []
    for m in _NUM_UNIT.finditer(text or ""):
        tok = m.group(0).strip()
        if _norm(tok) not in seen:
            seen.add(_norm(tok))
            out.append(tok)
    return out


def _pick_chunks(chunks: list, n: int) -> list:
    """优先选「有数值、有规范性措辞、正文够长」的块，并尽量分散在不同章节。"""
    scored = []
    for c in chunks:
        text = getattr(c, "text", "") or ""
        if len(text) < 30:
            continue
        anchors = _anchor_tokens(text)
        score = 0
        if anchors:
            score += 3
        if re.search(r"应当|不得|须|应于|至少|不超过", text):
            score += 2
        if 60 <= len(text) <= 400:
            score += 1
        if score:
            scored.append((score, c, anchors))
    scored.sort(key=lambda x: -x[0])

    picked, used_sections = [], set()
    for _score, chunk, anchors in scored:
        section = getattr(chunk, "section", "")
        if section in used_sections and len(picked) < n:
            continue
        used_sections.add(section)
        picked.append((chunk, anchors))
        if len(picked) >= n:
            break
    if len(picked) < n:  # 章节不够分散时放宽
        for _score, chunk, anchors in scored:
            if all(chunk is not p[0] for p in picked):
                picked.append((chunk, anchors))
            if len(picked) >= n:
                break
    return picked


def _extract_json(text: str) -> dict | None:
    raw = (text or "").strip()
    for candidate in [raw] + re.findall(r"\{[^{}]*\}", raw) + [_JSON_RE.search(raw).group(0)
                                                              if _JSON_RE.search(raw) else ""]:
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _llm_case(chunk) -> dict | None:
    prompt = (f"【资料标题】{chunk.title}\n【章节】{chunk.section}\n"
              f"【正文】{chunk.text[:600]}\n\n请输出 JSON。")
    try:
        text, _usage = chat(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
            temperature=0.0,
        )
    except Exception:  # noqa: BLE001 —— 生成失败就交给 heuristic 兜底
        return None
    obj = _extract_json(text)
    if not obj:
        return None
    question = str(obj.get("question") or "").strip()
    if len(question) < 6:
        return None
    # 关键词必须在原文里真实出现，否则这条断言是假的
    keywords = [str(k).strip() for k in (obj.get("keywords") or []) if str(k).strip()]
    keywords = [k for k in keywords if _norm(k) in _norm(chunk.text)][:3]
    if not keywords:
        return None
    return {"question": question, "keywords": keywords, "generated_by": "llm"}


def _unique_anchor(anchors: list[str]) -> str | None:
    """挑一个「同类数值只出现一次」的锚点。

    表格里常见「3 个工作日 / 5 个工作日」并列，随便挑一个出题会导致
    「答对了另一个也算失败」——这种断言是假失败，必须避免。
    """
    by_kind: dict[str, list[str]] = {}
    for token in anchors:
        by_kind.setdefault(_unit_kind(token), []).append(token)
    singles = [tokens[0] for tokens in by_kind.values() if len(tokens) == 1]
    return max(singles, key=len) if singles else None


def _heuristic_case(chunk, anchors: list[str]) -> dict | None:
    token = _unique_anchor(anchors)
    if not token:
        return None
    kind = _unit_kind(token)
    section = (chunk.section or "").strip()
    where = f"「{section}」" if section else "文中"
    question = f"《{chunk.title}》{where}规定的{kind}是多少？"
    return {"question": question, "keywords": [token], "generated_by": "heuristic"}


def _next_id(existing: list[dict]) -> int:
    nums = []
    for case in existing:
        m = re.fullmatch(r"D(\d+)", str(case.get("id", "")))
        if m:
            nums.append(int(m.group(1)))
    return max(nums, default=0) + 1


def load_cases(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def generate_for_document(doc_id: str, chunks: list, out_path: str | Path,
                          n: int = 3, prefer_llm: bool = True) -> dict:
    """为一份文档生成 n 条用例并追加到 out_path。返回 {cases, added, skipped, mode}。"""
    # 多取候选：部分块可能因为「同类数值并列」无法出可断言的题，需要向后补
    picked = _pick_chunks(list(chunks), max(n * 3, n + 3))
    if not picked:
        return {"added": 0, "cases": [], "mode": None,
                "reason": "没有可用于出题的知识块（内容过短或缺少可断言事实）"}

    out_path = Path(out_path)
    existing = load_cases(out_path)
    seen = {_norm(c.get("input", "")) for c in existing}
    next_id = _next_id(existing)

    use_llm = bool(prefer_llm and api_key())
    generated: list[dict] = []
    modes: set[str] = set()

    for chunk, anchors in picked:
        item = _llm_case(chunk) if use_llm else None
        if not item:
            item = _heuristic_case(chunk, anchors)
        if not item:
            continue
        modes.add(item["generated_by"])
        if _norm(item["question"]) in seen:
            continue
        seen.add(_norm(item["question"]))
        generated.append({
            "id": f"D{next_id:03d}",
            "category": "doc",
            "input": item["question"],
            "expect": {"behavior": "answer", "output_contains": item["keywords"]},
            "source": "upload",
            "doc_id": doc_id,
            "doc_section": getattr(chunk, "section", ""),
            "generated_by": item["generated_by"],
            "note": "上传文档自动生成；删除对应文档后该用例会被跳过",
        })
        next_id += 1
        if len(generated) >= n:
            break

    if generated:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "a", encoding="utf-8") as f:
            for case in generated:
                f.write(json.dumps(case, ensure_ascii=False) + "\n")

    return {
        "added": len(generated),
        "cases": generated,
        "mode": "+".join(sorted(modes)) if modes else None,
        "reason": None if generated else "模型与兜底都没能产出可断言的题",
    }
