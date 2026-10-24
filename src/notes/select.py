"""选择与归一化：把智能体传来的对话切成「用户真正想存的那几段」。

选择是产品的核心动作——不让人挑，存下来的就是一堆没用的聊天记录。
所以这里把「选哪些」做成显式参数（下标 / 区间 / 关键词），并在指纹里体现，
同一段内容重复保存会被识别成重复而不是新增。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MAX_MESSAGES = 200
MAX_CHARS_DEFAULT = 20000

_ROLES = {"user", "assistant", "system", "tool", "developer"}


class SelectError(ValueError):
    """选择参数不合法，消息可直接回给调用方。"""


@dataclass
class Msg:
    role: str
    text: str


def normalize(raw) -> list[Msg]:
    items = raw.get("messages") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise SelectError("messages 必须是数组，例如 [{\"role\":\"user\",\"text\":\"...\"}]")
    if not items:
        raise SelectError("messages 为空，没有可整理的内容")
    if len(items) > MAX_MESSAGES:
        raise SelectError(f"消息过多（{len(items)} 条），单次最多 {MAX_MESSAGES} 条，请先选择要保存的片段")
    result: list[Msg] = []
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise SelectError(f"第 {position} 条消息不是对象")
        role = str(item.get("role") or "user").strip().lower()
        if role not in _ROLES:
            role = "user"
        text = _extract_text(item)
        if not text.strip():
            continue
        result.append(Msg(role, text.strip()))
    if not result:
        raise SelectError("所有消息内容都为空，没有可整理的内容")
    return result


def _extract_text(item: dict) -> str:
    for key in ("text", "content"):
        value = item.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = []
            for part in value:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            return "\n".join(parts)
    return ""


def pick(messages: list[Msg], spec: dict | None) -> list[Msg]:
    if not spec or not spec.get("mode") or spec.get("mode") == "all":
        return list(messages)
    mode = str(spec["mode"])
    if mode == "indices":
        chosen = _by_indices(messages, spec.get("indices"))
    elif mode == "range":
        chosen = _by_range(messages, spec.get("start"), spec.get("end"))
    elif mode == "keyword":
        keyword = str(spec.get("keyword") or "").strip()
        if not keyword:
            raise SelectError("keyword 模式需要提供 keyword")
        chosen = [msg for msg in messages if keyword in msg.text]
    else:
        raise SelectError(f"未知的 select.mode：{mode}（可选 all / indices / range / keyword）")
    if not chosen:
        raise SelectError("按当前选择条件没有选中任何消息")
    return chosen


def _by_indices(messages: list[Msg], indices) -> list[Msg]:
    if not isinstance(indices, list) or not indices:
        raise SelectError("indices 模式需要提供下标数组，从 1 开始计数")
    picked = []
    for raw in indices:
        try:
            position = int(raw)
        except (TypeError, ValueError):
            raise SelectError(f"下标必须是整数：{raw!r}") from None
        if position < 1 or position > len(messages):
            raise SelectError(f"下标 {position} 超出范围（共 {len(messages)} 条）")
        picked.append(messages[position - 1])
    return picked


def _by_range(messages: list[Msg], start, end) -> list[Msg]:
    try:
        first = int(start)
        last = int(end)
    except (TypeError, ValueError):
        raise SelectError("range 模式需要 start 与 end 两个整数下标（含两端，从 1 开始）") from None
    if first < 1 or last < first or last > len(messages):
        raise SelectError(f"区间 {first}-{last} 不合法（共 {len(messages)} 条）")
    return messages[first - 1:last]


def fingerprint(messages: list[Msg]) -> str:
    """内容指纹：只跟选中的内容有关，跟标题、标签、时间都无关。"""
    digest = hashlib.sha256()
    for msg in messages:
        digest.update(msg.role.encode("utf-8"))
        digest.update(b"\x1f")
        digest.update(re.sub(r"\s+", " ", msg.text).strip().encode("utf-8"))
        digest.update(b"\x1e")
    return "sha256:" + digest.hexdigest()


def clip(text: str, limit: int = MAX_CHARS_DEFAULT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip() + "\n\n…（内容过长，已截断）", True


def render_transcript(messages: list[Msg]) -> str:
    """原文存档用：保留说话人，方便人回看是谁说的。"""
    labels = {"user": "用户", "assistant": "助手", "system": "系统", "tool": "工具", "developer": "开发者"}
    return "\n\n".join(f"**{labels.get(msg.role, msg.role)}**：{msg.text}" for msg in messages)
