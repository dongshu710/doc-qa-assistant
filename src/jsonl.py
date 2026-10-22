"""JSONL 日志读写：按大小轮转 + 从文件尾部读 N 行。

为什么不能继续用 `read_text().splitlines()[-N:]`：
- trace/audit 是长期追加的，读全文件会让 `/api/metrics`、`/api/audit` 的延迟
  随运行时长线性变差（13 MB 实测 56 ms，200 MB 就是秒级）；
- 一次读全文件也是一次内存峰值，服务跑得越久越危险。

轮转是为了给「尾读」一个上界：单文件不超过 `LOG_MAX_BYTES`，历史进 `.1/.2/.3`，
`tail_lines` 从尾部按块反向读，凑够行数就停，不再受文件总大小影响。
"""
from __future__ import annotations

import os
import threading

_BLOCK = 64 * 1024          # 单次反向读取块大小
_MAX_READ = 8 * 1024 * 1024  # 尾读最多回退这么多字节，防止「整个文件只有一行」时读爆内存

_rotate_lock = threading.Lock()


def tail_lines(path: str, limit: int, max_bytes: int = _MAX_READ,
               block_size: int = _BLOCK) -> list[str]:
    """返回文件末尾 `limit` 行（旧 → 新），只读必要的字节。

    行尾换行不计入；空行丢弃。文件不存在或读失败返回空列表，不抛异常——
    日志读取失败不该让接口 500。
    """
    limit = max(1, int(limit))
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    if size <= 0:
        return []

    buf = b""
    pos = size
    # 多读一行：文件末尾通常带换行，split 后会多出一个空段
    need = limit + 1
    budget = min(size, max(1, int(max_bytes)))
    try:
        with open(path, "rb") as f:
            while pos > 0 and buf.count(b"\n") < need and budget > 0:
                step = min(block_size, pos, budget)
                pos -= step
                budget -= step
                f.seek(pos)
                buf = f.read(step) + buf
    except OSError:
        return []

    raw = [line for line in buf.split(b"\n") if line.strip()]
    if pos > 0 and raw:
        # 读到了预算边界，第一段可能被截断；丢半行比解析出坏 JSON 更安全
        raw = raw[1:]
    return [line.decode("utf-8", errors="replace") for line in raw[-limit:]]


def tail_json(path: str, limit: int, **kwargs) -> list[dict]:
    """尾读并解析为 dict；坏行跳过（同一次写入被截断时会出现）。"""
    import json

    rows: list[dict] = []
    for line in tail_lines(path, limit, **kwargs):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def rotate(path: str, max_bytes: int, keep: int) -> bool:
    """超过上限就轮转：`x.jsonl` → `x.jsonl.1`，最老的 `.keep` 被删。

    返回是否真的轮转过。`max_bytes<=0` 表示关闭轮转。
    """
    if max_bytes <= 0 or keep <= 0:
        return False
    try:
        if os.path.getsize(path) < max_bytes:
            return False
    except OSError:
        return False
    with _rotate_lock:
        oldest = f"{path}.{keep}"
        if os.path.exists(oldest):
            try:
                os.remove(oldest)
            except OSError:
                pass
        for index in range(keep - 1, 0, -1):
            src = f"{path}.{index}"
            if os.path.exists(src):
                try:
                    os.replace(src, f"{path}.{index + 1}")
                except OSError:
                    pass
        try:
            os.replace(path, f"{path}.1")
        except OSError:
            return False
    return True


def append_line(path: str, line: str, max_bytes: int = 0, keep: int = 3) -> bool:
    """追加一行（自动带换行），必要时先轮转。返回是否写入成功。"""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    rotate(path, max_bytes, keep)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line.rstrip("\n") + "\n")
        return True
    except OSError:
        return False
