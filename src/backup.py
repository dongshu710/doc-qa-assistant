"""存储区备份与恢复：把「笔记 + 会话 + 导出」打成一个 zip，可搬走、可回滚。

为什么不是「导出全部笔记」：导出只覆盖 Markdown，会话在 `threads/`、清单在 `index/`，
用户误删或换机时需要的是「整个存储区回到昨天」，不是一堆散文件。

范围与取舍：
- 收 `notes/ threads/ exports/`；不收 `index/`（可由笔记重建）、`assets/`（可能很大）；
- 备份写进 `<home>/exports/backups/`，并在打包时排除该目录，避免自己套自己；
- 恢复只接受该目录里的包，解压前逐条校验成员路径（挡 zip slip），
  并且先自动做一份 pre-restore 备份——恢复本身也可能是误操作。
"""
from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime
from pathlib import Path

INCLUDE = ("notes", "threads", "exports")
SKIP_PARTS = {("exports", "backups")}
MAX_FILES = 20000
MAX_BYTES = 512 * 1024 * 1024


class BackupError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def backup_dir(home) -> Path:
    return Path(home) / "exports" / "backups"


def _iter_files(home: Path, root: str):
    base = home / root
    if not base.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = Path(dirpath).relative_to(home)
        if tuple(rel_dir.parts) in SKIP_PARTS:
            dirnames[:] = []
            continue
        for name in filenames:
            path = Path(dirpath) / name
            try:
                if path.is_symlink() or not path.is_file():
                    continue
            except OSError:
                continue
            yield path.relative_to(home)


def create(home, note: str = "") -> dict:
    home = Path(home).resolve()
    if not home.is_dir():
        raise BackupError("存储区不存在", 404)
    folder = backup_dir(home)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # 秒级时间戳会撞名：restore 里「先自动备份再解压」与用户刚点的备份常在同一秒，
    # 撞名就会把正在读的包覆盖掉（表现为 BadZipFile / CRC 错）。
    seq = 0
    while True:
        suffix = f"-{seq}" if seq else ""
        name = f"backup-{stamp}{suffix}.zip"
        target = folder / name
        if not target.exists():
            break
        seq += 1
    files = 0
    total = 0
    manifest = {
        "schema": "backup/v1",
        "created": datetime.now().isoformat(timespec="seconds"),
        "home": str(home),
        "note": str(note or "")[:200],
        "roots": list(INCLUDE),
    }
    try:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for root in INCLUDE:
                for rel in _iter_files(home, root):
                    path = home / rel
                    try:
                        size = path.stat().st_size
                    except OSError:
                        continue
                    if size > MAX_BYTES or files >= MAX_FILES:
                        raise BackupError("存储区过大，请分批备份（单包上限 20000 个文件 / 512 MB）", 413)
                    zf.write(path, rel.as_posix())
                    files += 1
                    total += size
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    except OSError as exc:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise BackupError(f"打包失败：{exc}", 500) from exc
    if not files:
        target.unlink(missing_ok=True)
        raise BackupError("存储区里还没有可备份的内容", 400)
    size = target.stat().st_size
    return {"name": name, "path": str(target), "bytes": size, "files": files,
            "source_bytes": total, "created": manifest["created"]}


def list_backups(home) -> list[dict]:
    folder = backup_dir(home)
    if not folder.is_dir():
        return []
    items = []
    for path in sorted(folder.glob("backup-*.zip"), reverse=True):
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append({"name": path.name, "path": str(path), "bytes": stat.st_size,
                      "created": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")})
    return items[:50]


def _check_members(zf: zipfile.ZipFile, home: Path) -> list[zipfile.ZipInfo]:
    """解压前逐条校验：不能绝对路径、不能 ..、必须落在允许的根目录下。"""
    out = []
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if info.is_dir():
            continue
        if name.startswith("/") or ".." in Path(name).parts:
            raise BackupError(f"备份包里有非法路径：{name}", 400)
        if name == "manifest.json":
            continue
        top = Path(name).parts[0]
        if top not in INCLUDE:
            raise BackupError(f"备份包含未知目录：{name}", 400)
        out.append(info)
    if not out:
        raise BackupError("备份包是空的", 400)
    return out


def restore(home, name: str, force: bool = False) -> dict:
    home = Path(home).resolve()
    safe = Path(str(name or "")).name
    if not safe or not safe.endswith(".zip"):
        raise BackupError("请指定备份文件名（*.zip）", 400)
    source = backup_dir(home) / safe
    if not source.is_file():
        raise BackupError("备份文件不存在", 404)

    with zipfile.ZipFile(source) as zf:
        members = _check_members(zf, home)
        existing = sum(1 for info in members if (home / info.filename).exists())
        if existing and not force:
            raise BackupError(
                f"有 {existing} 个文件已存在；确认覆盖请加 force=true（会先自动备份当前状态）", 409)
        pre = None
        try:
            pre = create(home, note=f"restore 前的自动备份（来源 {safe}）")
        except BackupError:
            pre = None            # 当前为空或不可打包时不阻断恢复
        written = 0
        for info in members:
            target = home / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".restore-tmp")
            with zf.open(info) as src, open(tmp, "wb") as dst:
                while True:
                    chunk = src.read(1024 * 256)
                    if not chunk:
                        break
                    dst.write(chunk)
            os.replace(tmp, target)
            written += 1
    return {"restored": written, "source": safe,
            "pre_backup": (pre or {}).get("name"),
            "message": f"已恢复 {written} 个文件" + (f"，恢复前状态存为 {pre['name']}" if pre else "")}
