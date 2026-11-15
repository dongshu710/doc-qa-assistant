"""结构化访问日志：一行一个请求。

为什么需要：`log_message` 原来是 `pass`——服务端**一行访问记录都没有**。
于是「流式回答 500 了」在服务端不留痕迹，只能靠用户说「刚才那次失败了」；
排查 SSE 断开、慢请求、某个接口被反复调用，全都没有证据。

设计取舍：
- **只记 path，不记 query**。`/api/search/debug?q=用户问题` 会把提问原文写进日志，
  而提问是 PII；要看检索细节有 trace.jsonl 与调试台，不靠访问日志。
- 写 stderr 一份、落 `access.jsonl` 一份：前者让前台启动能看到实时流量，
  后者能被 jsonl 的轮转机制管教（默认 8 MB × 3 份），不会长成几十 G。
- `ACCESS_LOG=off` 可以彻底关掉（离线包里不需要）。
- 每行自己带 `ms`：慢请求不用另做统计，`jq 'select(.ms>1000)'` 就够。
"""
from __future__ import annotations

import json
import os
import sys

from . import jsonl

_LOG_BYTES = 8 * 1024 * 1024
_LOG_KEEP = 3
_OFF = {"off", "0", "false", "no"}


def enabled() -> bool:
    return (os.environ.get("ACCESS_LOG", "on") or "on").strip().lower() not in _OFF


def emit(log_dir: str, *, method: str, path: str, status: int, ms: float,
         client: str, req_id: str = "") -> None:
    """写一条访问记录。任何异常都必须吞掉——日志坏了不能影响请求。"""
    if not enabled():
        return
    record = {
        "ts": _now(),
        "method": (method or "")[:10],
        "path": (path or "").split("?", 1)[0][:200],
        "status": int(status or 0),
        "ms": round(float(ms), 1),
        "client": client or "-",
    }
    if req_id:
        record["req_id"] = req_id[:32]
    line = json.dumps(record, ensure_ascii=False)
    if log_dir:
        try:
            jsonl.append_line(os.path.join(log_dir, "access.jsonl"), line,
                              max_bytes=_LOG_BYTES, keep=_LOG_KEEP)
        except (OSError, ValueError):
            pass
    # 只有真的接在终端上才往 stderr 打。
    # 为什么不是无条件打：stderr 被重定向到管道（`| tee`、IDE 捕获、subprocess.PIPE）
    # 而没人读时，管道缓冲一满，写日志的请求线程就整块阻塞——整个服务跟着停。
    # 实测（Windows 匿名管道缓冲默认 4KB）十几行日志就把 SSE 流卡住了：
    # 页面永远停在「正在组织答案并校验引用…」，而 CPU 全闲、日志里也没有错误。
    # 文件那份照写：那才是给人查的东西。
    try:
        if sys.stderr.isatty():
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
    except (OSError, ValueError, AttributeError):
        pass


def _now() -> str:
    from .timeutil import utc_now_iso

    return utc_now_iso()
