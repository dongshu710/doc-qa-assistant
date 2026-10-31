"""统一用例层：MCP / HTTP / CLI 三个入口都只调这里，避免三套行为漂移。

一次保存的完整链路：归一化 → 按选择条件切片 → 规则摘要 → 组装 Note → 落盘/预览。
`commit=False` 时只渲染不写盘，这是「先给人看一眼再存」的基础能力。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from . import assets as assets_mod
from . import digest_llm
from .model import KINDS, STATUSES, Note, NoteError
from .search import TEXT_MAX, NoteSearcher
from .select import (MAX_CHARS_DEFAULT, Msg, SelectError, clip, fingerprint,
                     normalize, pick, render_transcript)
from .store import NoteStore, SaveResult, _now_text, _read_note, new_id

DIGEST_MODES = ("rule", "auto", "llm")
SEMANTIC_MODES = ("auto", "off")


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
    meta: dict


class NoteService:
    def __init__(self, home: str | None = None, keep_raw: bool | None = None,
                 digest_mode: str | None = None):
        self.store = NoteStore(home, keep_raw=keep_raw)
        self.digest_mode = (digest_mode or os.environ.get("NOTE_DIGEST") or "rule").strip().lower()
        # 注入点：测试与自定义部署可以换成自己的模型调用，不必改这里的分支
        self.chat_call = None
        # 检索用的向量通道：默认走 settings 里的 embedding 配置；
        # 测试注入一个 `texts -> vectors` 的函数即可，不必真联网。
        self.embed_call = None
        self._search: NoteSearcher | None = None

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

        hint = payload.get("hint") or {}
        if not isinstance(hint, dict):
            raise NoteError("hint 必须是对象，例如 {\"title\":\"…\",\"tags\":[\"…\"]}")
        clipped = _clip_messages(selected)
        data, meta = digest_llm.digest(clipped, hint, mode=mode, call=self.chat_call)

        # 创建和修改必须用同一套枚举：否则 PATCH 拒绝的值能从 POST 溜进来，
        # 列表按 status 过滤时就永远查不到这篇（文件里还是非法值）
        status = str(hint.get("status") or "draft")
        if status not in STATUSES:
            raise NoteError(f"status 只能是 {' / '.join(STATUSES)}")

        raw_flag = self.store.keep_raw if keep_raw is None else keep_raw
        note = Note(
            id="",
            title=data["title"],
            created="",
            kind=data.get("kind") if data.get("kind") in KINDS else "qa",
            status=status,
            tags=data["tags"],
            source=_source(payload.get("source"), len(selected)),
            digest=meta["engine"],
        )
        if meta.get("fallback"):
            # 回落必须留痕：以后看文件能知道这篇是规则引擎兜的，不是模型写的
            note.extra["digest_fallback"] = meta["fallback"]
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
        return ComposeResult(note, selected, truncated, note.to_markdown(), meta)

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
            "digest_fallback": composed.meta.get("fallback"),
            "digest_ms": composed.meta.get("ms"),
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
            "assets": assets_mod.list_for(self.store.home, note.id),
            "markdown": note.to_markdown(),
        }

    # ---- 附件 ----

    def save_asset(self, note_id: str, filename: str, data: bytes) -> dict:
        """存附件前先确认笔记存在：孤儿附件既搜不到也导不出，等于往磁盘里扔垃圾。"""
        self.store.get(note_id)
        saved = assets_mod.save(self.store.home, note_id, filename, data)
        return {**saved, "note_id": note_id}

    def list_assets(self, note_id: str) -> list[dict]:
        self.store.get(note_id)
        return assets_mod.list_for(self.store.home, note_id)

    def read_asset(self, note_id: str, name: str) -> tuple[bytes, str]:
        self.store.get(note_id)
        return assets_mod.read(self.store.home, note_id, name)

    def delete_asset(self, note_id: str, name: str) -> dict:
        self.store.get(note_id)
        return assets_mod.delete(self.store.home, note_id, name)

    def rel_path(self, note_id: str) -> str:
        """相对存储区的路径。只给界面用（页内改原文），不参与导出。"""
        return self.store.rel_path(note_id)

    def list(self, **filters) -> list[dict]:
        return self.store.list(**filters)

    # ---- 检索 ----

    def searcher(self) -> NoteSearcher:
        """惰性构造检索索引；每次取用都把当前的 embed 注入同步过去。

        为什么不构造时固定：测试与宿主会在创建 service 之后再设 `embed_call`，
        构造时捕获会一直用旧的（通常是 None），表现为「注入了但还是没语义」。
        """
        if self._search is None:
            self._search = NoteSearcher(self.store.home, self._search_text, lock=self.store.lock)
        self._search._embed_call = self.embed_call   # noqa: SLF001 —— 故意做成可随时替换
        return self._search

    def _search_text(self, entry: dict) -> str:
        """把一篇笔记压成检索文本。读 .md 而不是索引：正文只存在文件里。"""
        try:
            note = _read_note(self.store.home / str(entry.get("path") or ""))
        except (OSError, KeyError, ValueError):
            return ""      # 单篇读不出来就跳过，不许拖垮整次检索
        # 附件名也进检索文本：用户常按「那份架构图 / 那个 pdf」找笔记
        names = [str(item.get("display") or item.get("name") or "")
                 for item in assets_mod.list_for(self.store.home, note.id)]
        return _doc_text(note, names)

    def search(self, query: str = "", tags=None, kind=None, status=None, since=None,
               limit: int = 20, semantic: str = "auto") -> dict:
        """先按标签/类型/日期筛出候选，再按 `query` 排序。

        为什么先筛后排：用户说「上周那篇讲部署的」时，日期与标签是硬约束。
        先在全库上按向量排完再过滤，既慢，又会把「日期对不上」的笔记顶到前面。
        """
        if semantic not in SEMANTIC_MODES:
            raise NoteError(f"semantic 只能是 {' / '.join(SEMANTIC_MODES)}")
        query = (query or "").strip()
        candidates = self.list(tags=tags, kind=kind, status=status, since=since, limit=0)
        if not query:
            return {"items": candidates[:limit] if limit else candidates,
                    "search": {"mode": "filter", "degraded": "", "indexed": 0,
                               "pending": 0, "total": len(candidates)}}
        outcome = self.searcher().search(query, candidates, semantic=semantic)
        ranked = sorted(
            ({"score": round(outcome.scores.get(row["id"], 0.0), 4), **row}
             for row in candidates if outcome.scores.get(row["id"], 0.0) > 0),
            key=lambda item: (-item["score"], str(item.get("created") or "")),
        )
        return {"items": ranked[:limit] if limit else ranked, "search": outcome.as_dict()}

    def rebuild_search(self, semantic: str = "auto") -> dict:
        """全量重建检索索引；`semantic=off` 时只重建文本、不碰向量。"""
        if semantic not in SEMANTIC_MODES:
            raise NoteError(f"semantic 只能是 {' / '.join(SEMANTIC_MODES)}")
        rows = self.list(limit=0)
        count, degraded, skipped = self.searcher().rebuild(rows, want_vec=semantic != "off")
        # skipped 一定要回给调用方：那几篇不会出现在任何搜索结果里，
        # 而「重建完成」的提示会让人以为全都进去了。
        return {"notes": count, "semantic": semantic != "off",
                "degraded": degraded, "skipped": skipped}

    def delete(self, note_id: str) -> dict:
        path = self.store.delete(note_id)
        return {"id": note_id, "trashed": str(path)}

    def stats(self) -> dict:
        return self.store.stats()


def _clip_messages(messages: list[Msg], per_message: int = 4000) -> list[Msg]:
    return [Msg(msg.role, msg.text[:per_message]) for msg in messages]


def _doc_text(note: Note, asset_names: list[str] | None = None) -> str:
    """检索文本的组装口径。

    标题与标签放在最前面：2-gram 检索里位置不参与打分，但把它们拼进同一段文本后，
    「标签：税务」这样的前缀能让 2-gram「税务」自然出现在正文之前，
    也让向量模型优先看到主题词。截断到 `TEXT_MAX`，避免一篇长笔记把预算吃光。

    附件名单独成一段：它们是独立的检索入口（「那张架构图」）。
    塞进正文里会和引用语法 `![...](assets/...)` 的哈希路径混在一起，反而更难命中。
    """
    parts = [f"标题：{note.title}"]
    if note.tags:
        parts.append("标签：" + " ".join(note.tags))
    if note.kind:
        parts.append(f"类型：{note.kind}")
    summary = note.summary
    if summary:
        parts.append("摘要：" + summary)
    if asset_names:
        parts.append("附件：" + " ".join(name for name in asset_names if name))
    for section in note.sections:
        parts.append(section.title)
        parts.append(section.body)
    return "\n".join(parts)[:TEXT_MAX]


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
