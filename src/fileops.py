"""存储区里的文件操作：读原文、写原文、交给系统默认编辑器打开。

为什么单独一层：用户要求「文件支持自由修改」，那就得让页面能编辑磁盘上的真文件。
但这不是文件管理器——只允许在存储区根目录以内、只允许文本后缀，
所有路径都先 resolve 再比较前缀，挡掉 `../../.ssh/id_rsa` 这种。

并发用内容哈希做乐观锁：写入带 base_rev，文件被别处改过就 409，
和笔记的 rev 语义保持一致，用户不用学第二套规则。
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".json", ".jsonl", ".csv", ".yaml", ".yml"}
MAX_READ_BYTES = 2 * 1024 * 1024


class FileError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _home(home) -> Path:
    return Path(home).expanduser().resolve()


def resolve(home, rel: str) -> Path:
    """把相对路径钉在存储区内。绝对路径、越界、符号链接逃逸一律拒绝。"""
    text = str(rel or "").strip().replace("\\", "/")
    if not text:
        raise FileError("缺少 path")
    if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        raise FileError("只接受存储区内的相对路径")
    root = _home(home)
    target = (root / text).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise FileError("路径超出了存储区") from None
    if target.suffix.lower() not in TEXT_SUFFIXES:
        raise FileError("只能在页面里编辑文本文件（.md / .txt / .json / .csv）")
    return target


def _rev(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def read(home, rel: str) -> dict:
    target = resolve(home, rel)
    try:
        stat = target.stat()
    except FileNotFoundError:
        raise FileError("文件不存在", 404) from None
    except OSError as exc:
        raise FileError(f"读取失败：{exc}", 500) from exc
    if stat.st_size > MAX_READ_BYTES:
        raise FileError("文件超过 2 MB，请用本地编辑器打开", 413)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise FileError(f"读取失败：{exc}", 500) from exc
    return {
        "path": str(target.relative_to(_home(home))).replace(os.sep, "/"),
        "content": raw.decode("utf-8", "replace"),
        "rev": _rev(raw),
        "size": len(raw),
        "mtime": int(stat.st_mtime),
    }


def write(home, rel: str, content: str, base_rev: str = "", create: bool = False) -> dict:
    """整篇覆盖写。已有文件必须带 base_rev，否则拒绝——乐观锁不是可选项。

    为什么默认拒绝：`base_rev` 一旦可选，漏传它的调用方（智能体、脚本、旧版前端）
    就会静默覆盖别人刚写的内容，而文档里还写着「冲突返回 409」。
    真正新建文件用 `create=True` 明确表达意图，两者不混。
    """
    target = resolve(home, rel)
    if target.exists():
        if create:
            raise FileError("文件已经存在，换个名字或直接编辑它", 409)
        if not base_rev:
            raise FileError("覆盖已有文件必须带 base_rev（先读一次拿到 rev）", 428)
        try:
            current = target.read_bytes()
        except OSError as exc:
            raise FileError(f"读取失败：{exc}", 500) from exc
        if _rev(current) != base_rev:
            raise FileError("文件在你编辑期间被改过（可能是智能体或别的编辑器），已拒绝覆盖", 409)
    elif base_rev:
        # 带着旧 rev 来写一个已经不存在的文件：多半是别处删了，别悄悄把它复活
        raise FileError("文件已不存在（可能已被删除或改名），请刷新后再试", 409)
    data = str(content if content is not None else "").encode("utf-8")
    if len(data) > MAX_READ_BYTES:
        raise FileError("内容超过 2 MB", 413)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    return {"path": str(target.relative_to(_home(home))).replace(os.sep, "/"),
            "rev": _rev(data), "size": len(data)}


def open_external(home, rel: str) -> str:
    """交给系统默认程序打开：改 Markdown 用顺手的编辑器，比在网页里挤着改舒服。"""
    target = resolve(home, rel)
    if not target.exists():
        raise FileError("文件不存在", 404)
    try:
        if os.name == "nt":
            os.startfile(str(target))  # noqa: S606 —— 用户点的是自己存储区里的文件
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except OSError as exc:
        raise FileError(f"系统没有可用的打开方式：{exc}", 500) from exc
    return str(target)
