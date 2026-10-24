"""笔记的数据模型与 Markdown 往返。

这是整个工具里最不该出错的一层：文件会被用户手工编辑、被多个智能体共同读写，
所以解析必须**容错优先**——格式坏了就降级成 external 笔记，绝不抛异常把数据卡死。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

SCHEMA = "note/v1"
SECTION_ORDER = ("摘要", "要点", "决策", "待办", "原文", "引用")
KINDS = ("decision", "howto", "reference", "qa", "log")
STATUSES = ("draft", "final", "archived")

_FRONT_MATTER = re.compile(r"^---\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.S)
_SECTION_HEAD = re.compile(r"^##[ \t]+(.+?)[ \t]*$")
_UNSAFE_CHARS = set(':#[]{}\r\n\t"\'')
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~"}


class NoteError(ValueError):
    """笔记数据不合法。消息面向调用方，必须能直接读。"""


@dataclass
class Section:
    title: str
    body: str = ""


@dataclass
class Note:
    id: str
    title: str
    created: str
    updated: str = ""
    kind: str = "qa"
    status: str = "draft"
    tags: list[str] = field(default_factory=list)
    source: dict = field(default_factory=dict)
    digest: str = "rule"
    hash: str = ""
    sections: list[Section] = field(default_factory=list)
    preface: str = ""
    extra: dict = field(default_factory=dict)
    external: bool = False
    schema: str = SCHEMA

    # ---- 读取 ----

    def section(self, title: str) -> str:
        for item in self.sections:
            if item.title == title:
                return item.body.strip()
        return ""

    @property
    def summary(self) -> str:
        """索引里存的一行摘要：优先「摘要」段，其次「要点」首条。"""
        body = self.section("摘要")
        if body:
            return re.sub(r"\s+", " ", body)[:160]
        points = self.section("要点")
        first = next((line.strip("- ").strip() for line in points.splitlines() if line.strip()), "")
        return first[:160]

    def bullets(self, title: str) -> list[str]:
        body = self.section(title)
        if not body:
            return []
        return [line.strip().lstrip("-").strip() for line in body.splitlines() if line.strip().startswith("-")]

    # ---- 写入 ----

    def set_section(self, title: str, body: str) -> None:
        body = body.strip()
        for item in self.sections:
            if item.title == title:
                item.body = body
                return
        self.sections.append(Section(title, body))

    def touch(self, stamp: str) -> None:
        self.updated = stamp

    # ---- 序列化 ----

    def to_markdown(self) -> str:
        lines = ["---", f"schema: {self.schema}", f"id: {self.id}",
                 f"title: {_emit(self.title)}", f"created: {self.created}",
                 f"updated: {self.updated or self.created}", f"kind: {self.kind}",
                 f"status: {self.status}"]
        if self.tags:
            lines.append("tags: [" + ", ".join(_emit(tag) for tag in self.tags) + "]")
        if self.source:
            lines.append("source:")
            for key, value in self.source.items():
                if value in ("", None):
                    continue
                lines.append(f"  {key}: {_emit(value)}")
        lines.append(f"digest: {self.digest}")
        for key, value in self.extra.items():
            if key in _KNOWN_FRONT_KEYS:
                continue
            lines.append(f"{key}: {_emit(value)}")
        if self.hash:
            lines.append(f"hash: {self.hash}")
        lines.append("---")
        body: list[str] = []
        if self.preface.strip():
            body.append(self.preface.strip())
        ordered = [s for name in SECTION_ORDER for s in self.sections if s.title == name]
        rest = [s for s in self.sections if s.title not in SECTION_ORDER]
        for item in ordered + rest:
            if not item.body.strip():
                continue
            body.append(f"## {item.title}")
            body.append(item.body.strip())
        return "\n".join(lines) + "\n\n" + "\n\n".join(body) + "\n"

    @classmethod
    def from_markdown(cls, text: str, fallback_id: str = "") -> "Note":
        """任何情况下都返回一个 Note；解析不了的字段一律降级，不抛异常。"""
        text = text.replace("\r\n", "\n")
        front, body = _split_front_matter(text)
        meta: dict = {}
        broken = False
        if front is not None:
            try:
                meta = _parse_front_matter(front)
            except Exception:  # noqa: BLE001 —— 用户手改出错是常态，不能因此读不出内容
                broken = True
                meta = {}
        note = cls(
            id=str(meta.get("id") or fallback_id or ""),
            title=str(meta.get("title") or ""),
            created=str(meta.get("created") or ""),
            updated=str(meta.get("updated") or ""),
            kind=str(meta.get("kind") or "qa"),
            status=str(meta.get("status") or "draft"),
            tags=[str(x) for x in (meta.get("tags") or []) if str(x).strip()],
            source=meta.get("source") if isinstance(meta.get("source"), dict) else {},
            digest=str(meta.get("digest") or "rule"),
            hash=str(meta.get("hash") or ""),
            extra={k: v for k, v in meta.items() if k not in _KNOWN_FRONT_KEYS},
            schema=str(meta.get("schema") or SCHEMA),
            external=broken or front is None,
        )
        note.preface, note.sections = _parse_body(body)
        if not note.title:
            note.title = _title_from_body(note.preface, note.sections) or (fallback_id or "未命名笔记")
        if note.kind not in KINDS:
            note.kind = "qa"
        if note.status not in STATUSES:
            note.status = "draft"
        return note


_KNOWN_FRONT_KEYS = {"schema", "id", "title", "created", "updated", "kind", "status",
                     "tags", "source", "digest", "hash"}


def _emit(value) -> str:
    """按需加引号：标题里常见冒号与井号，裸写会被下一个解析器当成结构。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    needs_quote = (
        text == "" or text != text.strip() or any(ch in _UNSAFE_CHARS for ch in text)
        or text[0] in "-?&*!|>%@`" or text.lower() in _RESERVED
        or re.fullmatch(r"-?\d+(\.\d+)?", text) is not None
    )
    return json.dumps(text, ensure_ascii=False) if needs_quote else text


def _split_front_matter(text: str) -> tuple[str | None, str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        return None, text
    return match.group(1), text[match.end():]


def _split_inline(text: str) -> list[str]:
    parts, buf, quote = [], [], ""
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        parts.append("".join(buf))
    return parts


def _parse_scalar(raw: str):
    raw = raw.strip()
    if raw == "":
        return ""
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [_parse_scalar(item) for item in _split_inline(inner)] if inner else []
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001 —— 用户可能只写了半个引号
            return raw.strip('"')
    if raw.startswith("'"):
        return raw[1:-1].replace("''", "'") if raw.endswith("'") else raw[1:]
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def _parse_front_matter(front: str) -> dict:
    meta: dict = {}
    parent: str | None = None
    for line in front.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indented = line[:1] in (" ", "\t")
        stripped = line.strip()
        if ":" not in stripped:
            raise ValueError(f"无法解析的 front matter 行: {stripped[:40]}")
        key, _, value = stripped.partition(":")
        key = key.strip()
        if indented:
            if parent is None:
                raise ValueError("缩进字段缺少父级")
            if not isinstance(meta.get(parent), dict):
                meta[parent] = {}
            meta[parent][key] = _parse_scalar(value)
            continue
        if value.strip() == "":
            parent = key
            meta[key] = {}
        else:
            parent = None
            meta[key] = _parse_scalar(value)
    return meta


def _parse_body(body: str) -> tuple[str, list[Section]]:
    preface: list[str] = []
    sections: list[Section] = []
    current: Section | None = None
    for line in body.split("\n"):
        match = _SECTION_HEAD.match(line)
        if match:
            current = Section(match.group(1).strip(), "")
            sections.append(current)
            continue
        if current is None:
            preface.append(line)
        else:
            current.body += line + "\n"
    for item in sections:
        item.body = item.body.strip()
    return "\n".join(preface).strip(), sections


def _title_from_body(preface: str, sections: list[Section]) -> str:
    for source in (preface, *(s.body for s in sections)):
        for line in source.split("\n"):
            cleaned = line.strip().lstrip("#").strip()
            if cleaned:
                return cleaned[:40]
    return ""
