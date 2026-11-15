"""原子写盘：同盘临时文件 → `os.replace`，撞上占用时重试。

为什么单独一个模块：这条逻辑在仓库里有十来份实现，其中两份（`guards._atomic_write`
与 `kbstore._atomic_json`）用的是固定名字 `path + ".tmp"`——同一个目标的两次并发写
会互相覆盖临时文件，把别人的半截内容换到正式位置。`threadstore._replace_with_retry`
早就把「唯一临时名 + 占用重试」两件事都处理了，但只有它自己在用。

所以这里只做两件事，别的都不做：
1. 临时名唯一（`tempfile.mkstemp`），并发写互不干扰；
2. Windows 上目标被别的进程持有（编辑器预览、杀软、同步盘）时短暂重试，
   而不是让用户看到「服务内部错误」——他多半只是开着那个文件。
"""
from __future__ import annotations

import json
import os
import tempfile
import time

# 4 次、总退避约 0.2 秒：够跨过一次杀软扫描，又不至于让请求明显变慢。
REPLACE_RETRIES = 4
REPLACE_BACKOFF_S = 0.02


def replace_with_retry(src: str, dst: str, retries: int = REPLACE_RETRIES) -> None:
    """`os.replace`，撞上「文件被占用」时短暂重试。

    只重试 PermissionError：目录不存在、跨盘之类的错误重试也没用，
    早点抛出去比让调用方等 0.2 秒更好。
    """
    last: OSError | None = None
    for attempt in range(max(1, int(retries))):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:
            last = exc
            time.sleep(REPLACE_BACKOFF_S * (attempt + 1))
    raise last if last is not None else OSError(f"无法替换 {dst}")


def write_bytes(path: str, data: bytes) -> None:
    """原子写入字节。

    不调 `fsync`：这些文件都是「可重建的派生数据或可重放的配置」，
    掉电丢最后一次写入可以接受；而 fsync 在 Windows 上单次 5–20ms，
    `CostBudget` 每秒落一次盘，会把这笔开销摊到正在收尾的请求上。
    """
    target = os.path.abspath(path)
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)
    # 前缀以 "." 开头：kbstore 的 _prune 按 startswith("v") 扫描版本目录，
    # 临时文件不能长得像版本号。
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        replace_with_retry(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path: str, data, indent: int = 2) -> None:
    write_bytes(path, json.dumps(data, ensure_ascii=False, indent=indent).encode("utf-8"))
