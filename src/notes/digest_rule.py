"""规则摘要：不依赖大模型的那条腿。

它的价值不是「聪明」，而是**永不失败**——没有 Key、断网、模型抽风时，
笔记照样能生成、能读、能被下一个智能体接手。所以这里所有分支都返回结果，
不抛异常，也不做任何网络调用。

启发式的取向：优先取助手说过的话（用户的提问不适合当要点），
问句不进要点与待办，决策句不重复进待办。
"""

from __future__ import annotations

import re

from .model import KINDS
from .select import Msg, clip

_SENTENCE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
_CONCLUSION = ("结论", "因此", "所以", "确定", "采用", "定为", "统一", "最终",
               "建议", "需要", "必须", "不得", "标准", "上限", "下限", "比例", "期限", "金额")
_DECISION = re.compile(r"决定|采用|定为|改成|改为|拍板|敲定|以.{0,12}为准")
_TODO = re.compile(r"待办|todo|下一步|待确认|需要确认|跟进|落实|复核|补充材料|提交|完成时间", re.I)
_URL = re.compile(r"https?://[^\s<>\)\"']+")
_LEAD = re.compile(r"^[\s\-*•·\d.、)）]+")
_TODO_LEAD = re.compile(r"^(待办|todo|下一步)[:：]\s*", re.I)


def digest(messages: list[Msg], hint: dict | None = None) -> dict:
    hint = hint or {}
    assistant_text = "\n".join(msg.text for msg in messages if msg.role == "assistant")
    user_text = "\n".join(msg.text for msg in messages if msg.role != "assistant")
    # 要点优先来自助手的回答；纯用户输入（例如转存的笔记片段）再回落到全部内容
    sentences = _clean_sentences(assistant_text) or _clean_sentences(user_text)
    if len(sentences) < 3 and user_text:
        for sentence in _clean_sentences(user_text):
            if sentence not in sentences:
                sentences.append(sentence)

    decisions = _matched(sentences, _DECISION, 3)
    todos = _matched(sentences, _TODO, 3, exclude=set(decisions))
    points = _points(sentences, exclude=set(decisions) | set(todos), limit=5)
    summary = _summary(points, decisions, todos, assistant_text or user_text)

    sections = {"摘要": summary}
    if points:
        sections["要点"] = "\n".join(f"- {_short(item, 90)}" for item in points)
    if decisions:
        sections["决策"] = "\n".join(f"- {_short(item, 90)}" for item in decisions)
    if todos:
        sections["待办"] = "\n".join(f"- [ ] {_short(_TODO_LEAD.sub('', item), 90)}" for item in todos)
    refs = _refs(assistant_text + "\n" + user_text)
    if refs:
        sections["引用"] = "\n".join(f"- {url}" for url in refs)

    return {
        "title": _title(messages, hint),
        "kind": hint.get("kind") if hint.get("kind") in KINDS else "qa",
        "tags": _tags(hint.get("tags")),
        "sections": sections,
        "digest": "rule",
    }


def _clean_sentences(text: str) -> list[str]:
    rows = []
    for match in _SENTENCE.finditer(text):
        sentence = re.sub(r"\s+", " ", match.group(0)).strip()
        sentence = _LEAD.sub("", sentence).strip()
        if 6 <= len(sentence) <= 300:
            rows.append(sentence)
    return rows


def _is_question(sentence: str) -> bool:
    return sentence.rstrip().endswith(("？", "?"))


def _score(sentence: str, index: int, total: int) -> int:
    score = 0
    if re.search(r"\d", sentence):
        score += 2
    if any(word in sentence for word in _CONCLUSION):
        score += 2
    if 12 <= len(sentence) <= 90:
        score += 1
    if total and index / total < 0.3:
        score += 1
    if sentence.endswith(("。", "！", "？")):
        score += 1
    return score


def _points(sentences: list[str], exclude: set[str], limit: int) -> list[str]:
    if not sentences:
        return []
    total = len(sentences)
    ranked = sorted(
        ((_score(sentence, i, total), i, sentence) for i, sentence in enumerate(sentences)
         if sentence not in exclude and not _is_question(sentence) and not _low_value(sentence)),
        key=lambda item: (-item[0], item[1]),
    )
    picked: list[str] = []
    seen: set[str] = set()
    for _, _, sentence in ranked:
        key = re.sub(r"\W+", "", sentence)[:16]
        if key in seen:
            continue
        seen.add(key)
        picked.append(sentence)
        if len(picked) >= limit:
            break
    picked.sort(key=sentences.index)
    return picked


def _matched(sentences: list[str], pattern: re.Pattern, limit: int,
             exclude: set[str] | None = None) -> list[str]:
    rows, seen = [], set()
    skip = exclude or set()
    for sentence in sentences:
        if sentence in skip or _is_question(sentence) or not pattern.search(sentence):
            continue
        key = re.sub(r"\W+", "", sentence)[:16]
        if key in seen:
            continue
        seen.add(key)
        rows.append(sentence)
        if len(rows) >= limit:
            break
    return rows


def _low_value(sentence: str) -> bool:
    """去掉链接后没剩几个字的句子，多半只是引用，不该占要点位置。"""
    return len(re.sub(r"https?://\S+", "", sentence).strip(" 。，；:：-")) < 8


def _summary(points: list[str], decisions: list[str], todos: list[str], text: str) -> str:
    candidates = [*points, *decisions, *todos]
    picked, seen = [], set()
    for item in candidates:
        key = re.sub(r"\W+", "", item)[:16]
        if key in seen or _low_value(item):
            continue
        seen.add(key)
        picked.append(item)
        if len(picked) >= 2:
            break
    if picked:
        return "；".join(_short(item, 60).rstrip("。；;") for item in picked) + "。"
    body, _ = clip(re.sub(r"\s+", " ", text).strip(), 120)
    return body


def _title(messages: list[Msg], hint: dict) -> str:
    raw = str(hint.get("title") or "").strip()
    # 调用方显式给的标题按 schema 的 120 字上限保留，只有自动取名才压到 24 字。
    # 网页的标题输入框写的是 maxlength=120、PATCH 也放行 120，创建时却截到 24 会是同一个字段两套规则。
    explicit = bool(raw)
    if not raw:
        first = next((msg.text for msg in messages if msg.role == "user"), messages[0].text)
        first = re.split(r"[。！？!?\n]", first.strip(), maxsplit=1)[0]
        raw = first
    raw = re.sub(r"^[#\s]+", "", raw)
    raw = re.sub(r"\s+", " ", raw).strip("《》「」“”\"'` ")
    return _short(raw, 120 if explicit else 24) or "未命名笔记"


def _tags(raw) -> list[str]:
    if not raw:
        return []
    tags, seen = [], set()
    for item in raw:
        tag = str(item).strip().lstrip("#").replace(" ", "")[:16]
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) >= 8:
            break
    return tags


def _refs(text: str) -> list[str]:
    seen, rows = set(), []
    for url in _URL.findall(text):
        url = url.rstrip(".,;，。；")
        if url in seen:
            continue
        seen.add(url)
        rows.append(url)
        if len(rows) >= 8:
            break
    return rows


def _short(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"
