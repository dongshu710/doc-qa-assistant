"""存储内核：目录约定、原子写、目录锁、索引自愈。

设计取舍：写入永远先落临时文件再 replace，避免进程被杀时留下半个 .md；
索引坏了或被人删掉都能从磁盘重建，所以这里所有读路径都允许「没有索引」。
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .. import appconfig
from ..locks import STALE_DEFAULT_S, break_stale, identity

from . import index as index_mod
from .model import Note

DEFAULT_HOME = "~/agent-notes"
# 与知识库锁、索引锁共用同一个阈值：三处都是「同一份数据、不同入口」，
# 各自维护一个数字迟早会出现「这边还在写、那边已经判死」。
LOCK_STALE_SECONDS = STALE_DEFAULT_S
# 重建要读全盘：Windows 上单次 open 的固定开销远大于解析本身，少量线程即可摊掉
REBUILD_WORKERS = 4


class NoteNotFound(KeyError):
    def __init__(self, note_id: str):
        super().__init__(note_id)
        self.note_id = note_id

    def __str__(self) -> str:
        return f"找不到笔记：{self.note_id}"


class DuplicateNote(RuntimeError):
    def __init__(self, note_id: str, path: Path):
        super().__init__(f"内容已存在：{note_id}")
        self.note_id = note_id
        self.path = path


class StoreBusy(RuntimeError):
    pass


@dataclass
class SaveResult:
    note: Note
    path: Path | None
    created: bool = True
    duplicate_of: str | None = None


class NoteStore:
    def __init__(self, home: str | Path | None = None, keep_raw: bool | None = None):
        # 优先级：显式参数 > 界面里选的存储位置 > NOTE_HOME > ~/agent-notes。
        # 界面排在环境变量前面，否则用户在设置里换了位置却发现没生效。
        raw_home = (str(home) if home
                    else appconfig.get("notes.home")
                    or os.environ.get("NOTE_HOME")
                    or DEFAULT_HOME)
        self.home = Path(raw_home).expanduser().resolve()
        self.keep_raw = keep_raw if keep_raw is not None else _env_flag("NOTE_KEEP_RAW", False)
        self._cache: dict[str, dict] | None = None
        self._cache_stat: tuple[int, int] | None = None
        self._cache_lines = 0
        self._ensure_dirs()

    # ---- 路径 ----

    @property
    def notes_dir(self) -> Path:
        return self.home / "notes"

    @property
    def trash_dir(self) -> Path:
        return self.home / ".trash"

    def _ensure_dirs(self) -> None:
        for path in (self.notes_dir, self.home / "index", self.home / "assets",
                     self.home / "exports", self.trash_dir):
            path.mkdir(parents=True, exist_ok=True)
        guide = self.home / "AGENTS.md"
        if not guide.exists():
            # 只写一次：用户改过就不再覆盖，这份说明本身也是可编辑的文件
            from .schema_doc import HOME_README
            guide.write_text(HOME_README, encoding="utf-8")

    def path_for(self, note: Note) -> Path:
        match = re.match(r"^(\d{4})-(\d{2})", note.created or "")
        if match:
            year, month = match.group(1), match.group(2)
        else:
            stamp = _now()
            year, month = stamp.strftime("%Y"), stamp.strftime("%m")
        return self.notes_dir / year / month / f"{note.id}.md"

    # ---- 锁 ----

    @contextmanager
    def lock(self, timeout: float = 5.0):
        """跨进程互斥：目录创建是原子操作，比平台相关的文件锁更好移植。

        释放时核对身份：这把锁可能已经被判定超时、被别人清掉并重建，
        此时直接 rmtree 删的是别人的锁，于是两边同时认为自己持有。
        """
        lock_dir = self.home / ".lock"
        deadline = time.monotonic() + timeout
        while True:
            try:
                os.mkdir(lock_dir)
                break
            except FileExistsError:
                try:
                    # 这里必须用 time.time()：比的是文件 mtime，那是墙钟
                    if time.time() - lock_dir.stat().st_mtime > LOCK_STALE_SECONDS:
                        break_stale(lock_dir, is_dir=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise StoreBusy("另一个写入正在进行，请稍后重试") from None
                time.sleep(0.05)
        mine = identity(lock_dir)
        try:
            yield
        finally:
            if mine is not None and identity(lock_dir) == mine:
                shutil.rmtree(lock_dir, ignore_errors=True)

    # ---- 索引缓存 ----

    def _entries(self) -> dict[str, dict]:
        path = index_mod.index_path(self.home)
        try:
            stat = path.stat()
        except FileNotFoundError:
            self._cache, self._cache_stat, self._cache_lines = {}, None, 0
            return self._cache
        signature = (stat.st_mtime_ns, stat.st_size)
        if self._cache is None or signature != self._cache_stat:
            self._cache, self._cache_lines = index_mod.read(self.home)
            self._cache_stat = signature
        return self._cache

    def _note_index_sync(self) -> None:
        """让缓存跟随刚写出的索引文件，省掉下一次全量读取。"""
        try:
            stat = index_mod.index_path(self.home).stat()
            self._cache_stat = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            self._cache_stat = None

    # ---- 写 ----

    def save(self, note: Note, check_duplicate: bool = True) -> SaveResult:
        if not note.id:
            note.id = new_id()
        note.touch(_now_text())
        path = self.path_for(note)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock():
            # 查重和写入必须在同一把锁里：网页与 MCP 同时存同一段对话时，
            # 锁外查重会各自查到「不存在」，然后各写一篇，去重形同虚设。
            if check_duplicate and note.hash:
                existing = self.find_by_hash(note.hash)
                if existing and (self.home / existing["path"]).exists():
                    existing_path = self.home / existing["path"]
                    return SaveResult(_read_note(existing_path), existing_path, created=False,
                                      duplicate_of=str(existing["id"]))
            tmp = path.with_suffix(".md.tmp")
            with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(note.to_markdown())
            os.replace(tmp, path)
            entries = self._entries()
            entry = index_mod.entry_for(note, path, self.home)
            index_mod.append(self.home, entry)
            entries[note.id] = entry
            self._cache_lines += 1
            self._note_index_sync()
            if index_mod.needs_compact(self._cache_lines, len(entries)):
                index_mod.write_all(self.home, entries)
                self._cache_lines = len(entries)
                self._note_index_sync()
        return SaveResult(note, path, created=True)

    def delete(self, note_id: str) -> Path:
        """软删除：移入 .trash，人想找回还能找回。"""
        path = self._resolve(note_id)
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        target = self.trash_dir / f"{_now().strftime('%Y%m%d-%H%M%S')}-{note_id}.md"
        with self.lock():
            shutil.move(str(path), str(target))
            entries = self._entries()
            entries.pop(note_id, None)
            index_mod.write_all(self.home, entries)
            self._cache_lines = len(entries)
            self._note_index_sync()
        return target

    # ---- 读 ----

    def rel_path(self, note_id: str) -> str:
        """笔记文件相对存储区的路径；找不到就返回空串（页面据此隐藏编辑入口）。"""
        try:
            path = self._resolve(note_id)
        except (KeyError, OSError):
            return ""
        try:
            return str(path.relative_to(self.home)).replace(os.sep, "/")
        except ValueError:
            return ""

    def get(self, note_id: str) -> Note:
        return _read_note(self._resolve(note_id))

    def rev(self, note_id: str) -> str:
        """文件内容指纹，用于乐观锁：人改过、智能体改过都会让它变。"""
        return hashlib.sha256(self._resolve(note_id).read_bytes()).hexdigest()[:16]

    def _resolve(self, note_id: str) -> Path:
        entry = self._entries().get(note_id)
        if entry:
            path = self.home / entry["path"]
            if path.exists():
                return path
        # 索引删了、或文件是外部放进来的，扫盘兜底
        for candidate in sorted(self.notes_dir.rglob(f"{note_id}.md")):
            return candidate
        raise NoteNotFound(note_id)

    def list(self, tags: list[str] | None = None, kind: str | None = None,
             status: str | None = None, since: str | None = None,
             limit: int = 50) -> list[dict]:
        entries = dict(self._entries())
        if not entries and any(self.notes_dir.rglob("*.md")):
            # 索引被删或被清空：读路径自愈，用户不该为了「能列出」而先跑一条命令
            self.rebuild()
            entries = dict(self._entries())
        dirty = False
        for note_id, entry in list(entries.items()):
            path = self.home / entry["path"]
            try:
                stat = path.stat()
            except FileNotFoundError:
                entries.pop(note_id, None)
                dirty = True
                continue
            if stat.st_mtime_ns != entry.get("mtime_ns") or stat.st_size != entry.get("size"):
                note = _read_note(path)
                entries[note_id] = index_mod.entry_for(note, path, self.home)
                dirty = True
        if not entries and any(self.notes_dir.rglob("*.md")):
            self.rebuild()
            entries = dict(self._entries())
        if dirty:
            index_mod.write_all(self.home, entries)
            self._cache_lines = len(entries)
            self._note_index_sync()
        rows = [row for row in entries.values() if _match(row, tags, kind, status, since)]
        rows.sort(key=lambda row: str(row.get("created") or ""), reverse=True)
        return rows[:limit] if limit else rows

    def find_by_hash(self, content_hash: str) -> dict | None:
        for entry in self._entries().values():
            if entry.get("hash") == content_hash:
                return entry
        return None

    # ---- 维护 ----

    def rebuild(self) -> int:
        """从磁盘重建索引；外部新增/改名/删除的笔记都在这一步被收纳。"""
        entries: dict[str, dict] = {}
        paths = sorted(self.notes_dir.rglob("*.md"))
        with ThreadPoolExecutor(max_workers=REBUILD_WORKERS) as pool:
            for path, note in pool.map(_read_or_none, paths):
                if note is None:
                    continue
                if not note.id:
                    note.id = path.stem
                entries[note.id] = index_mod.entry_for(note, path, self.home)
        with self.lock():
            index_mod.write_all(self.home, entries)
        self._cache, self._cache_lines = entries, len(entries)
        self._note_index_sync()
        return len(entries)

    def stats(self) -> dict:
        rows = self.list(limit=0)
        by_kind: dict[str, int] = {}
        by_tag: dict[str, int] = {}
        for row in rows:
            by_kind[row.get("kind", "qa")] = by_kind.get(row.get("kind", "qa"), 0) + 1
            for tag in row.get("tags") or []:
                by_tag[tag] = by_tag.get(tag, 0) + 1
        return {"home": str(self.home), "notes": len(rows), "kinds": by_kind,
                "tags": dict(sorted(by_tag.items(), key=lambda kv: -kv[1])[:10])}


def _read_or_none(path: Path) -> tuple[Path, Note | None]:
    try:
        return path, _read_note(path)
    except OSError:
        return path, None


def _read_note(path: Path) -> Note:
    text = path.read_text(encoding="utf-8", errors="replace")
    note = Note.from_markdown(text, fallback_id=path.stem)
    if not note.id:
        note.id = path.stem
    if not note.created:
        note.created = datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    return note


def _match(row: dict, tags: list[str] | None, kind: str | None,
           status: str | None, since: str | None) -> bool:
    if tags and not set(tags).issubset(set(row.get("tags") or [])):
        return False
    if kind and row.get("kind") != kind:
        return False
    if status and row.get("status") != status:
        return False
    if since and str(row.get("created") or "")[:10] < since:
        return False
    return True


def new_id() -> str:
    return f"{_now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"


def _now() -> datetime:
    return datetime.now().astimezone()


def _now_text() -> str:
    return _now().isoformat(timespec="seconds")


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "on", "true", "yes")
