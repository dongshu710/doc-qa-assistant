"""派生索引：notes.jsonl。

只是缓存——删掉不丢数据，任何一条读路径都能从磁盘上的 .md 重建。
因此这里的策略是「宁可多读一次，也不可信地当成数据库」。
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def index_path(home: Path) -> Path:
    return home / "index" / "notes.jsonl"


def entry_for(note, path: Path, home: Path) -> dict:
    stat = path.stat()
    try:
        relative = str(path.relative_to(home))
    except ValueError:
        relative = str(path)
    return {
        "id": note.id,
        "path": relative.replace(os.sep, "/"),
        "title": note.title,
        "tags": list(note.tags),
        "kind": note.kind,
        "status": note.status,
        "created": note.created,
        "updated": note.updated or note.created,
        "digest": note.digest,
        "summary": note.summary,
        "hash": note.hash,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def read(home: Path) -> tuple[dict[str, dict], int]:
    """返回（按 id 去重后的条目，原始行数）。后写的行覆盖先写的行。"""
    path = index_path(home)
    entries: dict[str, dict] = {}
    lines = 0
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                lines += 1
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue  # 半行写入（进程被杀）不该让整个索引失效
                note_id = item.get("id")
                if note_id:
                    entries[note_id] = item
    except FileNotFoundError:
        return {}, 0
    return entries, lines


def append(home: Path, entry: dict) -> None:
    path = index_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def write_all(home: Path, entries: dict[str, dict]) -> None:
    path = index_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        for entry in entries.values():
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def needs_compact(lines: int, entries: int) -> bool:
    """追加行太多会让读取变慢，超过两倍且不少于 500 行时压缩一次。"""
    return lines > max(500, entries * 2)
