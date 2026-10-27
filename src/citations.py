"""引用支持度：答案里的 [n]，第 n 块资料到底支不支持。

为什么需要另做一层：现有校验只确认「编号在 1..len(hits) 范围内」，
所以 `citation_coverage = 1.0` 的真实含义是「格式全对」，而不是「引对了」。
模型完全可以用正确的编号引一段无关内容——这是 RAG 最危险、也最难被用户发现的失败。

判定用两条可复现的规则，不做语义模型调用（本地、零依赖、可进 CI）：
1. 句子里的数字/百分比/金额，必须在被引块里出现过（金融场景最要命的是数字）；
2. 句子与块的中文二元组覆盖率 ≥ 阈值（默认 0.55），否则视为「引了但没说同一件事」。

规则版会漏判（释义型改写会被判低覆盖），所以只作为**风险信号**：
默认只标记不拦截，`CITATION_STRICT=on` 时才降级为抽取式答案。
"""
from __future__ import annotations

import re

from .retriever import tokenize

REF = re.compile(r"\[(\d+)\]")
SENTENCE = re.compile(r"[^。！？!?\n]+[。！？!?]?")
# 数字后面跟单位时一起比，避免「90」和「90 天」被当成同一个事实
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%|％|元|万元|亿元|天|个月|年|期|bp|BP)?")
MIN_COVERAGE = 0.55


def _norm_number(text: str) -> str:
    text = text.replace(",", "").replace("％", "%")
    return re.sub(r"\s+", "", text)


def _numbers(text: str) -> set[str]:
    """抽取「事实数字」。先把 [n] 引用标记去掉，否则 [2] 里的 2 会被当成事实。"""
    body = REF.sub(" ", text or "")
    return {_norm_number(m.group(0)) for m in NUMBER.finditer(body) if m.group(0).strip()}


def _sentences(answer: str) -> list[str]:
    return [s.strip() for s in SENTENCE.findall(answer or "") if s.strip()]


def _coverage(sentence: str, chunk_text: str) -> float:
    q = set(tokenize(sentence))
    if not q:
        return 1.0
    return len(q & set(tokenize(chunk_text))) / len(q)


def verify(answer: str, hits) -> dict:
    """返回 {checked, supported, rate, items[]}。

    `hits` 是 [(chunk, score), ...]，编号从 1 开始，与答案里的 [n] 对齐。
    """
    items: list[dict] = []
    for sentence in _sentences(answer):
        refs = [int(x) for x in REF.findall(sentence)]
        if not refs:
            continue
        for ref in dict.fromkeys(refs):          # 同一句里的重复编号只算一次
            if not 1 <= ref <= len(hits):
                continue                          # 越界编号由 _finalize 的 valid 过滤负责
            chunk = hits[ref - 1][0]
            text = f"{chunk.title} {chunk.section} {chunk.text}"
            missing = sorted(n for n in _numbers(sentence) if n not in _norm_number(text))
            coverage = round(_coverage(sentence, text), 3)
            ok = not missing and coverage >= MIN_COVERAGE
            items.append({
                "ref": ref,
                "supported": ok,
                "coverage": coverage,
                "missing_facts": missing[:5],
            })
    checked = len(items)
    supported = sum(1 for item in items if item["supported"])
    return {
        "checked": checked,
        "supported": supported,
        "rate": round(supported / checked, 3) if checked else 1.0,
        "items": items,
    }
