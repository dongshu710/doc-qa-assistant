"""大模型摘要：只负责「让模型按固定 JSON 输出」，其余全部交给规则引擎兜底。

三条硬约束：
1. 输出必须是 JSON，且字段能过校验；任何不合规都回落规则摘要，不写半成品进文件。
2. 超时、限流、没有 Key 一律回落，绝不让「保存笔记」因为模型不可用而失败。
3. 回落是**可见**的：`note.digest` 仍是 rule，front matter 里额外记 `digest_fallback`。
"""

from __future__ import annotations

import json
import re
import time

from . import digest_rule
from .model import KINDS, SECTION_ORDER, NoteError
from .select import Msg

ALLOWED_SECTIONS = tuple(name for name in SECTION_ORDER if name != "原文")
MAX_TAGS = 8
MAX_TITLE = 120

SYSTEM = """你是笔记整理助手。输入是一段人与智能体的对话，你要把它整理成一篇能长期复用的中文笔记。

只输出一个 JSON 对象，不要 Markdown 代码块，不要任何解释。结构：
{
  "title": "20 字以内的标题，说清留下了什么结论或做法",
  "kind": "decision | howto | reference | qa | log",
  "tags": ["2-4 个短标签，不要 # 号"],
  "sections": {
    "摘要": "1-2 句，必须写",
    "要点": "- 每条一个事实，一行一条",
    "决策": "- 已定下来的结论（没有就不写这一节）",
    "待办": "- [ ] 可执行项（没有就不写这一节）",
    "引用": "- 链接或出处（没有就不写这一节）"
  }
}

要求：
- 只写对话里明确出现过的内容，不要补充背景知识，不要编数字、日期、金额。
- 摘要必须包含具体信息（对象 + 结论），不要写「讨论了……相关问题」这种空话。
- 不确定的内容宁可省略，也不要猜。
"""


def build_messages(messages: list[Msg], hint: dict) -> list[dict]:
    lines = []
    for index, msg in enumerate(messages, 1):
        role = {"user": "用户", "assistant": "助手", "system": "系统", "tool": "工具"}.get(msg.role, msg.role)
        lines.append(f"[{index}] {role}：{msg.text}")
    extra = []
    if hint.get("title"):
        extra.append(f"用户希望的标题：{hint['title']}")
    if hint.get("kind") in KINDS:
        extra.append(f"用户指定的类型：{hint['kind']}")
    if hint.get("tags"):
        extra.append("用户指定的标签：" + "、".join(str(tag) for tag in hint["tags"][:MAX_TAGS]))
    preamble = ("以下是对话记录：\n\n" + "\n\n".join(lines))
    if extra:
        preamble += "\n\n补充要求：\n" + "\n".join(f"- {item}" for item in extra)
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": preamble}]


def _strip_fence(text: str) -> str:
    """模型经常裹一层 ```json；剥掉再解析，别为格式小事整个回落。"""
    body = (text or "").strip()
    fence = re.match(r"^```(?:json|JSON)?\s*(.*?)\s*```$", body, re.S)
    if fence:
        return fence.group(1).strip()
    return body


def parse(text: str, hint: dict | None = None) -> dict:
    """把模型输出解析并校验成 digest_rule 同构的字典；不合规抛 ValueError。"""
    hint = hint or {}
    try:
        raw = json.loads(_strip_fence(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"输出不是合法 JSON：{exc.msg}") from exc
    if not isinstance(raw, dict):
        raise ValueError("输出顶层不是对象")

    title = re.sub(r"\s+", " ", str(raw.get("title") or hint.get("title") or "")).strip()
    title = title.strip("《》「」“”\"'` ")
    if not title:
        raise ValueError("缺少 title")
    title = title[:MAX_TITLE]

    kind = raw.get("kind") if raw.get("kind") in KINDS else hint.get("kind")
    if kind not in KINDS:
        kind = "qa"

    tags: list[str] = []
    for item in list(raw.get("tags") or [])[:MAX_TAGS * 2]:
        tag = str(item).strip().lstrip("#").strip()
        if tag and tag not in tags:
            tags.append(tag[:16])
    if not tags:
        for item in hint.get("tags") or []:
            tag = str(item).strip().lstrip("#").strip()
            if tag and tag not in tags:
                tags.append(tag[:16])

    sections_raw = raw.get("sections")
    if not isinstance(sections_raw, dict):
        raise ValueError("缺少 sections 对象")
    sections: dict[str, str] = {}
    for name, body in sections_raw.items():
        key = str(name).strip()
        if key not in ALLOWED_SECTIONS:
            continue
        text_body = str(body or "").strip()
        if text_body:
            sections[key] = text_body
    if not sections.get("摘要"):
        raise ValueError("摘要为空")

    return {"title": title, "kind": kind, "tags": tags[:MAX_TAGS], "sections": sections}


def digest(messages: list[Msg], hint: dict | None = None, mode: str = "auto",
           call=None, timeout_s: float | None = None) -> tuple[dict, dict]:
    """返回 (摘要数据, 元信息)。

    mode: auto = 有模型就用，失败静默回落；llm = 必须成功，否则抛 NoteError。
    """
    hint = hint or {}
    started = time.perf_counter()
    if mode == "rule":
        # 显式选了规则引擎就一次模型都不该调：否则「离线可用」是假的
        return _fallback(messages, hint, None, started, mode)
    if mode == "auto" and call is None and not _has_key():
        return _fallback(messages, hint, "no_key", started, mode)

    try:
        caller = call or _default_call
        text = caller(build_messages(messages, hint), timeout_s)
        data = parse(text, hint)
        return data, {"engine": "llm", "fallback": None, "mode": mode,
                      "ms": int((time.perf_counter() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001 —— 任何异常都不该让「保存」失败
        reason = _reason(exc)
        if mode == "llm":
            raise NoteError(
                f"大模型摘要失败（{reason}）；改用 --digest rule 可离线保存，"
                "或检查 LLM_API_KEY / 端点配置") from exc
        return _fallback(messages, hint, reason, started, mode)


def _fallback(messages: list[Msg], hint: dict, reason: str | None, started: float,
              mode: str) -> tuple[dict, dict]:
    data = digest_rule.digest(messages, hint)
    return data, {"engine": "rule", "fallback": reason or None, "mode": mode,
                  "ms": int((time.perf_counter() - started) * 1000)}


def _has_key() -> bool:
    try:
        from ..config import api_key
    except ImportError:  # pragma: no cover —— 单独拷走 notes 包时按无 Key 处理
        return False
    return bool(api_key())


def _default_call(messages: list[dict], timeout_s: float | None) -> str:
    from .. import generator
    text, _usage = generator.chat(messages, temperature=0.2, timeout_s=timeout_s)
    return text


def _reason(exc: Exception) -> str:
    name = type(exc).__name__
    if name == "RuntimeError" and "LLM_API_KEY" in str(exc):
        return "no_key"
    if name in ("TimeoutError", "socket.timeout") or "timed out" in str(exc).lower():
        return "timeout"
    if isinstance(exc, ValueError):
        return "invalid_output"
    if name in ("URLError", "HTTPError", "ConnectionError", "OSError"):
        return "network"
    return f"error:{name}"
