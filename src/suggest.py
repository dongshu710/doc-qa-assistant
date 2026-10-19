"""示例问题与相似问题：只依据已入库文档的章节与正文生成。

为什么不用硬编码示例：知识库可以随上传变化，示例问题必须跟着文档走。
这里用启发式模板（零 token、确定性），从章节标题和规范性措辞生成问题；
需要更自然的问法时，可在此模块替换为 LLM 生成，调用方接口不变。
"""
from __future__ import annotations

import re

from .retriever import tokenize

_SECTION_NO = re.compile(r"^[一二三四五六七八九十百零\d]+[、.．)）]\s*")
_NUM = re.compile(r"\d+(?:\.\d+)?\s*(?:亿元|万元|元|%|％|个工作日|工作日|小时|天|个月|年|日|份|倍)")
_GENERIC = {"", "概述", "前言", "总则", "说明"}


def _clean_section(section: str) -> str:
    return _SECTION_NO.sub("", (section or "").strip()).strip()


def _clean_title(title: str) -> str:
    return re.sub(r"^(?:pdf_|docx_)?(?:演示制度_|监管摘录_)+", "", (title or "").strip())


def _question_for(chunk) -> str | None:
    section = _clean_section(chunk.section)
    title = _clean_title(chunk.title)
    text = (chunk.text or "").strip()
    if not text:
        return None
    if not section or section in _GENERIC:
        return f"《{title}》主要规定了什么？"
    if re.search(r"流程|办理|申请|手续", section):
        return f"{section}需要哪些手续？"
    if re.search(r"期限|时限|频率|时间", section):
        return f"{section}的时限要求是什么？"
    if _NUM.search(text) and re.search(r"起购|起存|金额|比例|费率|上限|下限|标准", section + text):
        return f"{section}的具体标准是多少？"
    if re.search(r"应当|不得|须|至少|不超过", text):
        return f"{section}有哪些规定？"
    return f"{section}是怎么规定的？"


def _push(out: list[str], text: str | None, seen: set[str]) -> None:
    if not text:
        return
    key = re.sub(r"\s+", "", text)
    if key and key not in seen:
        seen.add(key)
        out.append(text)


def examples(chunks, n: int = 4) -> list[str]:
    """按文档分散取样，返回 n 条与当前知识库一致的示例问题。"""
    out: list[str] = []
    seen: set[str] = set()
    used_docs: set[str] = set()

    # 先每份文档取一条，保证示例覆盖不同文件
    for chunk in chunks:
        if len(out) >= n:
            break
        if chunk.doc_id in used_docs:
            continue
        q = _question_for(chunk)
        if q:
            used_docs.add(chunk.doc_id)
            _push(out, q, seen)

    # 不够再按章节补齐
    for chunk in chunks:
        if len(out) >= n:
            break
        if _clean_section(chunk.section) in _GENERIC:
            continue
        _push(out, _question_for(chunk), seen)

    for chunk in chunks:
        if len(out) >= n:
            break
        _push(out, _question_for(chunk), seen)
    return out[:n]


def similar(chunks, query: str, hits=None, n: int = 3) -> list[str]:
    """答不出来时给出「可以接着问」的相似问题。

    优先用低分召回块（说明它们与问题仍有字面关联），不足时按词重合度补。
    """
    q = set(tokenize(query))
    ranked = []

    for rank, item in enumerate(hits or []):
        chunk = item[0] if isinstance(item, tuple) else item
        overlap = len(q & set(tokenize(chunk.section + " " + chunk.text)))
        ranked.append((overlap, -rank, chunk))

    if not ranked:
        for chunk in chunks:
            overlap = len(q & set(tokenize(chunk.section + " " + chunk.text)))
            if overlap:
                ranked.append((overlap, 0, chunk))

    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)

    out: list[str] = []
    seen: set[str] = set()
    for _overlap, _rank, chunk in ranked:
        _push(out, _question_for(chunk), seen)
        if len(out) >= n:
            break
    if not out:
        return examples(chunks, n)
    return out
