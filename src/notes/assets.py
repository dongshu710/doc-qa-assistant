"""附件：图片与文件的落盘、去重与读取。

为什么按笔记 id 分目录：`notes://schema` 里早就写了 `assets/<id>/` 这个契约，
智能体是按它去找附件的；改成平铺等于把已经发出去的约定推翻。

为什么文件名前面加内容哈希：两张同名不同内容的图不能互相覆盖，同一张图插两次
也只占一份。前缀给人排序看，哈希给程序判重。改名只改后半段，哈希永远不动，
所以「同内容」永远能靠前缀找回来。

安全边界（这里每一条都对应一个真实攻击面）：
- `note_id` 走白名单正则——它会直接拼进路径；
- 文件名去掉分隔符与控制字符，且单独再校验一次不含 `/` `\\` `..`，
  文件名来自调用方，路径穿越只需要一个 `../`；
- 扩展名白名单，且**不含任何可执行类型**：这个目录会被导出、被备份、
  被别的程序读，放一个 `.exe` 进去没有任何正当理由；
- 单文件大小上限，防止一次请求把磁盘写满。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import mimetypes
import os
import re
from datetime import datetime
from pathlib import Path

SCHEMA_REF = "assets"
MAX_BYTES = 8 * 1024 * 1024          # 单个附件 8 MB：够放截图与常见文档
MAX_NAME = 80
# 只收「看一眼/读一下」的类型。可执行文件、脚本、快捷方式一律不收。
ALLOWED_EXT = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
    ".pdf", ".txt", ".md", ".csv", ".json", ".log",
    ".docx", ".xlsx", ".pptx", ".zip",
})
IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"})
# 能当纯文本读出来的：给 MCP 资源时用 text 而不是 blob，省去调用方再解一次 base64
TEXT_EXT = frozenset({".txt", ".md", ".csv", ".json", ".log"})
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]{0,80}$")
_BAD = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


class AssetError(ValueError):
    """附件相关的可预期错误；`status` 让 HTTP 层直接映射，不用猜。"""

    def __init__(self, message: str, status: int = 400, code: str = "invalid_asset"):
        super().__init__(message)
        self.status = status
        self.code = code


class AssetNotFound(AssetError):
    def __init__(self, name: str):
        super().__init__(f"找不到附件：{name}", status=404, code="asset_not_found")
        self.name = name


def asset_dir(home: str | Path, note_id: str) -> Path:
    return Path(home) / SCHEMA_REF / _check_id(note_id)


def _check_id(note_id: str) -> str:
    text = str(note_id or "")
    if not _ID.match(text):
        raise AssetError(f"笔记 id 不合法：{text}", status=400)
    return text


def sanitize(name: str) -> str:
    """清洗文件名：去掉路径分隔符与控制字符，压掉重复的点与空白。

    `a/../../b` → `a....b` 这种结果还要再过一遍 `_BAD` 与显式 `..` 检查；
    单靠正则替换挡不住所有写法，所以 `resolve()` 里还要再验一次。
    """
    base = os.path.basename(str(name or "").replace("\\", "/"))
    base = _BAD.sub("_", base).strip().strip(".")
    base = re.sub(r"\s+", " ", base)
    if not base:
        base = "file"
    stem, ext = os.path.splitext(base)
    ext = ext.lower()
    if not ext or ext not in ALLOWED_EXT:
        raise AssetError(f"不支持的文件类型：{ext or '（无扩展名）'}；"
                         f"允许 {' / '.join(sorted(ALLOWED_EXT))}")
    if len(stem) > MAX_NAME:
        stem = stem[:MAX_NAME]
    return f"{stem}{ext}"


def mime_of(name: str) -> str:
    guessed, _ = mimetypes.guess_type(str(name))
    if guessed:
        return guessed
    return "application/octet-stream"


def is_image(name: str) -> bool:
    return os.path.splitext(str(name))[1].lower() in IMAGE_EXT


def is_text(name: str) -> bool:
    return os.path.splitext(str(name))[1].lower() in TEXT_EXT


def ref(note_id: str, name: str) -> str:
    """写进 markdown 的相对路径。相对存储区根，导出时按同一套规则解析。"""
    return f"{SCHEMA_REF}/{note_id}/{name}"


def decode_data(raw) -> bytes:
    """把调用方给的 base64 解成字节；同时接受 `data:image/png;base64,xxx`。

    前端 FileReader.readAsDataURL 吐出来的是带前缀的形式。让每个调用方各自
    切一遍前缀，迟早会切得不一样，不如在这里收口。
    """
    if not isinstance(raw, str) or not raw.strip():
        raise AssetError("附件内容为空", status=400)
    text = raw.strip()
    if text.startswith("data:"):
        text = text.split(",", 1)[-1]
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AssetError(f"data 不是合法 base64：{exc}", status=400) from None


def save(home: str | Path, note_id: str, filename: str, data: bytes) -> dict:
    """存一个附件；内容相同则复用已有文件，不重复占空间。"""
    note_id = _check_id(note_id)
    if not isinstance(data, (bytes, bytearray)):
        raise AssetError("附件内容必须是字节", status=400)
    if not data:
        raise AssetError("文件是空的", status=400)
    if len(data) > MAX_BYTES:
        raise AssetError(f"文件太大：{len(data)} 字节，上限 {MAX_BYTES // (1024 * 1024)} MB",
                         status=413)
    safe = sanitize(filename)
    digest = hashlib.sha256(bytes(data)).hexdigest()
    folder = asset_dir(home, note_id)
    folder.mkdir(parents=True, exist_ok=True)

    prefix = digest[:8] + "-"
    for existing in folder.iterdir():
        if existing.is_file() and existing.name.startswith(prefix):
            return _entry(existing, note_id, digest)

    name = f"{prefix}{safe}"
    target = folder / name
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(bytes(data))
    os.replace(tmp, target)
    return _entry(target, note_id, digest)


def _entry(path: Path, note_id: str, digest: str) -> dict:
    name = path.name
    relative = ref(note_id, name)
    image = is_image(name)
    # 展示名去掉哈希前缀：用户在正文里看到的应该是「架构图.png」而不是「a1b2c3d4-架构图.png」
    display = name.split("-", 1)[1] if "-" in name else name
    return {
        "name": name,
        "display": display,
        "note_id": note_id,
        "size": path.stat().st_size,
        "sha256": digest,
        "mime": mime_of(name),
        "image": image,
        "ref": relative,
        "markdown": f"![{display}]({relative})" if image else f"[{display}]({relative})",
    }


def list_for(home: str | Path, note_id: str) -> list[dict]:
    folder = asset_dir(home, note_id)
    if not folder.is_dir():
        return []
    rows = []
    for path in folder.iterdir():
        if not path.is_file() or path.name.endswith(".tmp"):
            continue
        digest = path.name.split("-", 1)[0]
        rows.append(_entry(path, note_id, digest))
    rows.sort(key=lambda item: item["name"])
    return rows


def resolve(home: str | Path, note_id: str, name: str) -> Path:
    """把 URL 里的名字变成磁盘路径；任何越界尝试都拒绝。"""
    note_id = _check_id(note_id)
    text = str(name or "")
    if not text or text in (".", "..") or "/" in text or "\\" in text:
        raise AssetError(f"附件名不合法：{text}", status=400)
    if text.endswith(".tmp"):
        raise AssetError("临时文件不可读", status=400)
    folder = asset_dir(home, note_id).resolve()
    path = (folder / text).resolve()
    # 再核一次父目录：符号链接或不常见写法都可能让 resolve 之后跑出去
    if path.parent != folder:
        raise AssetError("附件名不合法：越界路径", status=400)
    if not path.is_file():
        raise AssetNotFound(text)
    return path


def read(home: str | Path, note_id: str, name: str) -> tuple[bytes, str]:
    path = resolve(home, note_id, name)
    return path.read_bytes(), mime_of(name)


def delete(home: str | Path, note_id: str, name: str) -> dict:
    path = resolve(home, note_id, name)
    path.unlink()
    return {"name": path.name, "deleted": True,
            "warning": "正文里对它的引用会变成失效链接，记得一并删掉"}


def stats(home: str | Path) -> dict:
    """给备份与「存储占用」用：总量、条数、最大单文件。"""
    base = Path(home) / SCHEMA_REF
    total = 0
    count = 0
    largest = 0
    if base.is_dir():
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            size = path.stat().st_size
            total += size
            count += 1
            largest = max(largest, size)
    return {"count": count, "bytes": total, "largest": largest}


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
