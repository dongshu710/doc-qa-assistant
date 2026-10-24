"""统一用例层：MCP / HTTP / CLI 三个入口都只调这里，避免三套行为漂移。

一次保存的完整链路：归一化 → 按选择条件切片 → 规则摘要 → 组装 Note → 落盘/预览。
`commit=False` 时只渲染不写盘，这是「先给人看一眼再存」的基础能力。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from . import digest_rule
from .model import KINDS, STATUSES, Note, NoteError
from .select import (MAX_CHARS_DEFAULT, Msg, SelectError, clip, fingerprint,
                     normalize, pick, render_transcript)
from .store import NoteStore, SaveResult, _now_text, new_id

DIGEST_MODES = ("rule", "auto", "llm")


class NoteConflict(RuntimeError):
    """乐观锁冲突：调用方拿到的 base_rev 与文件当前内容不一致。"""

    def __init__(self, rev: str):
        super().__init__(f"笔记已被修改（当前 rev={rev}），请重新读取后再改")
        self.rev = rev


@dataclass
class ComposeResult:
    note: Note
    selected: list[Msg]
    truncated: bool
    markdown: str


class NoteService:
    def __init__(self, home: str | None = None, keep_raw: bool | None = None,
                 digest_mode: str | None = None):
        self.store = NoteStore(home, keep_raw=keep_raw)
        self.digest_mode = (digest_mode or os.environ.get("NOTE_DIGEST") or "rule").strip().lower()

    # ---- 组装 ----

    def compose(self, payload: dict, keep_raw: bool | None = None,
                digest_mode: str | None = None) -> ComposeResult:
        if not isinstance(payload, dict):
            raise NoteError("请求体必须是 JSON 对象")
        try:
            messages = normalize(payload)
        except SelectError as exc:
            raise NoteError(str(exc)) from exc

        select_spec = payload.get("select") or {}
        try:
            selected = pick(messages, select_spec)
        except SelectError as exc:
            raise NoteError(str(exc)) from exc

        limit = int(select_spec.get("max_chars") or MAX_CHARS_DEFAULT)
        joined = "\n".join(msg.text for msg in selected)
        body, truncated = clip(joined, limit)

        mode = (digest_mode or payload.get("digest") or self.digest_mode or "rule").lower()
        if mode not in DIGEST_MODES:
            raise NoteError(f"未知的摘要模式：{mode}（可选 rule / auto / llm）")
        if mode in ("llm", "auto"):
            # 该分支属于下一里程碑：现在明确拒绝，不假装做过
            raise NoteError("当前版本只内置规则摘要（DIGEST=rule），大模型摘要尚未接入")

        hint = payload.get("hint") or {}
        if not isinstance(hint, dict):
            raise NoteError("hint 必须是对象，例如 {\"title\":\"…\",\"tags\":[\"…\"]}")
        data = digest_rule.digest(_clip_messages(selected), hint)

        raw_flag = self.store.keep_raw if keep_raw is None else keep_raw
        note = Note(
            id="",
            title=data["title"],
            created="",
            kind=data.get("kind") if data.get("kind") in KINDS else "qa",
            status=str(hint.get("status") or "draft"),
            tags=data["tags"],
            source=_source(payload.get("source"), len(selected)),
            digest="rule",
        )
        for name, text in data["sections"].items():
            note.set_section(name, text)
        if truncated:
            note.set_section("原文", render_transcript(selected)[:limit] + "\n\n…（已截断）")
        elif raw_flag:
            note.set_section("原文", render_transcript(selected))
        note.hash = fingerprint(selected)

        note.id = new_id()
        note.created = _now_text()
        note.updated = note.created
        return ComposeResult(note, selected, truncated, note.to_markdown())

    def save(self, payload: dict, commit: bool = True, keep_raw: bool | None = None,
             digest_mode: str | None = None) -> dict:
        composed = self.compose(payload, keep_raw=keep_raw, digest_mode=digest_mode)
        keep_raw_flag = self.store.keep_raw if keep_raw is None else keep_raw
        note = composed.note
        path = None
        duplicate_of = None
        committed = False
        raw_added = False

        if commit:
            result: SaveResult = self.store.save(composed.note)
            path = result.path
            if result.duplicate_of:
                # 重复时返回既有那篇：调用方要的是「东西在哪」，不是这次新生成的空 id
                duplicate_of = result.duplicate_of
                note = result.note
                # 先前没存原文、这次显式要求存：补进同一篇，而不是假装成功却什么都没变
                if keep_raw_flag and not note.section("原文"):
                    note.set_section("原文", composed.note.section("原文"))
                    note.touch(_now_text())
                    path = self.store.save(note, check_duplicate=False).path
                    raw_added = True
            else:
                committed = True

        return {
            "ok": True,
            "committed": committed,
            "id": note.id,
            "title": note.title,
            "kind": note.kind,
            "tags": note.tags,
            "digest": note.digest,
            "truncated": composed.truncated,
            "messages": len(composed.selected),
            "path": str(path) if path else None,
            "duplicate_of": duplicate_of,
            "raw_added": raw_added,
            "markdown": note.to_markdown() if duplicate_of else composed.markdown,
        }

    # ---- 修改 ----

    def patch(self, note_id: str, changes: dict, base_rev: str | None = None,
              force: bool = False) -> dict:
        """局部修改：只动传入的字段，其余原样保留。

        默认要求 base_rev（GET 返回的 rev），避免「人刚改完、智能体又按旧内容覆盖」。
        """
        if not isinstance(changes, dict) or not changes:
            raise NoteError("changes 不能为空，至少给一个字段（title / tags / status / kind / sections）")
        unknown = set(changes) - {"title", "tags", "status", "kind", "sections"}
        if unknown:
            raise NoteError(f"不支持的字段：{', '.join(sorted(unknown))}")
        current_rev = self.store.rev(note_id)
        if not force:
            if not base_rev:
                raise NoteError("需要 base_rev（由 GET 返回的 rev）做并发保护；确实要强改就传 force=true")
            if str(base_rev) != current_rev:
                raise NoteConflict(current_rev)

        note = self.store.get(note_id)
        if "title" in changes:
            title = str(changes["title"] or "").strip()
            if not title:
                raise NoteError("title 不能为空")
            note.title = title[:120]
        if "kind" in changes:
            if changes["kind"] not in KINDS:
                raise NoteError(f"kind 只能是 {' / '.join(KINDS)}")
            note.kind = str(changes["kind"])
        if "status" in changes:
            if changes["status"] not in STATUSES:
                raise NoteError(f"status 只能是 {' / '.join(STATUSES)}")
            note.status = str(changes["status"])
        if "tags" in changes:
            tags = changes["tags"]
            if not isinstance(tags, list):
                raise NoteError("tags 必须是字符串数组")
            cleaned = []
            for item in tags:
                tag = str(item).strip().lstrip("#")
                if tag and tag not in cleaned:
                    cleaned.append(tag[:16])
            note.tags = cleaned[:8]
        if "sections" in changes:
            sections = changes["sections"]
            if not isinstance(sections, dict):
                raise NoteError("sections 必须是对象，形如 {\"摘要\":\"正文\"}；传空字符串表示删除该节")
            for name, body in sections.items():
                key = str(name).strip()
                if not key:
                    raise NoteError("sections 的小节名不能为空")
                text = str(body or "").strip()
                existing = next((item for item in note.sections if item.title == key), None)
                if not text:
                    if existing is not None:
                        note.sections.remove(existing)
                    continue
                note.set_section(key, text)
        note.touch(_now_text())
        self.store.save(note, check_duplicate=False)
        return self.get(note_id)

    # ---- 查询 ----

    def get(self, note_id: str) -> dict:
        note = self.store.get(note_id)
        return {
            "id": note.id, "title": note.title, "kind": note.kind,
            "status": note.status, "tags": note.tags, "digest": note.digest,
            "created": note.created, "updated": note.updated,
            "external": note.external, "hash": note.hash,
            "rev": self.store.rev(note.id),
            "sections": [{"title": item.title, "body": item.body} for item in note.sections],
            "markdown": note.to_markdown(),
        }

    def list(self, **filters) -> list[dict]:
        return self.store.list(**filters)

    def delete(self, note_id: str) -> dict:
        path = self.store.delete(note_id)
        return {"id": note_id, "trashed": str(path)}

    def stats(self) -> dict:
        return self.store.stats()


def _clip_messages(messages: list[Msg], per_message: int = 4000) -> list[Msg]:
    return [Msg(msg.role, msg.text[:per_message]) for msg in messages]


def _source(raw, message_count: int) -> dict:
    source: dict = {}
    if isinstance(raw, dict):
        for key in ("agent", "model", "session", "app", "tool"):
            value = raw.get(key)
            if value in (None, ""):
                continue
            text = re.sub(r"\s+", " ", str(value)).strip()[:80]
            if text:
                source[key] = text
    source["messages"] = message_count
    return source
