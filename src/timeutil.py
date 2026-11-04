"""全项目统一的时间口径。

为什么单独一个模块：会话、知识库版本、向量索引都要写「最后更新时间」，
三份一模一样的 `datetime.now(timezone.utc).isoformat()` 分散在三个文件里。
1.28.0 踩过的坑正是时间基准不一致——`created` 是前端 `toISOString()`（UTC），
`updated` 是后端本地时间且不带时区，同一条记录里差 8 小时。
口径只能有一份，改的时候才不会漏掉其中一个。

不用 `datetime.utcnow()`：它返回 naive 对象，`.isoformat()` 出来的串没有 `+00:00`，
前端 `new Date()` 会按本地时区解释，又回到同一个坑里。
"""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now_iso() -> str:
    """当前 UTC 时间，ISO 8601 并带 `+00:00` 偏移。"""
    return datetime.now(timezone.utc).isoformat()
