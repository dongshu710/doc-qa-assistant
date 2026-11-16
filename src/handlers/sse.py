"""SSE 中继：把「生成在独立线程 + 主线程发心跳 + 断连即取消」这套骨架收敛成一处。

为什么合并：`/api/ask/stream`（内部 delta/replace/final）与
`/v1/chat/completions`（stream=true，OpenAI chunk）是同一件事的两种帧格式。
原来两份拷贝各自演化，取消语义已经分叉——内部那套在客户端断开时 `cancel.set()`，
OpenAI 那套只在「写失败」时置位，且两条路的收尾顺序（谁先记账、谁后发结束帧）
各写各的。两者都能用，但「改一处忘另一处」只是时间问题，代价是断开后模型仍把
这一轮 token 跑完（钱照记、线程照占）。

分工刻意划在「时序」与「协议」之间：

- 本模块只管**时序与生命周期**：生产线程、事件队列、心跳、总时长上限、取消、
  关闭生成器。这些错了会泄漏线程与名额，且很难从外部看出来。
- 调用方只管**协议**：帧怎么编码、结束帧怎么发、要不要回填用量、记不记账。

结束帧由调用方在 relay 返回后自己发——不是懒，而是顺序有讲究：
`_stream_answer` 必须「先标注、再记账、最后把 final 发给客户端」，
把发帧塞进 relay 就得把记账回调也塞进来，那才是真的耦合。
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .common import SSE_HEARTBEAT_S, SSE_MAX_SECONDS


@dataclass(slots=True)
class Outcome:
    """一次中继的结果。

    `broken` 与 `timed_out` 必须分开报：前者是「客户端走了」（正常现象，
    不该记错误），后者是「我们主动掐断」（要告诉用户为什么没答完）。
    """

    final: dict | None = None
    error: str = ""
    timed_out: bool = False
    broken: bool = False


def relay(*, factory: Callable[[], object],
          send: Callable[[str, object], None],
          cancel: threading.Event,
          heartbeat: Callable[[], None] | None = None,
          max_seconds: float | None = None,
          heartbeat_s: float | None = None,
          thread_name: str = "ask-stream") -> Outcome:
    """跑一条流，直到结束/超时/断开。

    - `factory()` 返回可迭代的 `(event, data)`，在**独立线程**里迭代；
    - `send(event, data)` 负责写一帧，写失败**必须抛 OSError**
      （中继靠它判断「客户端走了」，吞掉异常等于让生成继续烧 token）；
    - `heartbeat()` 每次空闲超过 `heartbeat_s` 调一次；OpenAI 客户端不解析
      SSE 注释，那条路传 None；
    - `cancel` 由这里置位，调用方也可以在收尾时自己置位（重复置位无害）。

    超时不在这里发帧：两套协议的「超时」帧形状不同，交给调用方按
    `outcome.timed_out` 自己发。
    """
    limit = SSE_MAX_SECONDS if max_seconds is None else max_seconds
    idle = SSE_HEARTBEAT_S if heartbeat_s is None else heartbeat_s
    events: queue.Queue = queue.Queue()
    outcome = Outcome()

    def produce() -> None:
        stream = None
        try:
            stream = factory()
            for item in stream:
                if cancel.is_set():
                    break
                events.put(item)
        except Exception as exc:  # noqa: BLE001 —— 生成线程的异常要回传给请求线程
            events.put(("__error__", str(exc)[:300]))
        finally:
            # 取消时关掉生成器：close() 触发 GeneratorExit，上游的模型请求立刻断开，
            # 而不是把整轮 token 跑完再丢掉。这一步漏了，取消就只是「不收结果」。
            if stream is not None:
                closer = getattr(stream, "close", None)
                if closer is not None:
                    try:
                        closer()
                    except Exception:  # noqa: BLE001
                        pass
            events.put(("__done__", None))

    threading.Thread(target=produce, name=thread_name, daemon=True).start()
    deadline = time.monotonic() + float(limit)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            outcome.timed_out = True
            cancel.set()
            break
        try:
            # 拿 `remaining` 一起等：只给 idle 的话，最后一个心跳之后还要再等一轮
            # 才检查超时，实际时长会超过上限一个心跳周期。
            event, data = events.get(timeout=min(float(idle), remaining))
        except queue.Empty:
            if heartbeat is not None:
                try:
                    heartbeat()
                except OSError:
                    outcome.broken = True
                    cancel.set()
                    break
            continue
        if event == "__done__":
            break
        if event == "__error__":
            outcome.error = str(data)
            cancel.set()
            break
        if event == "final":
            # 只收不发：调用方要在发之前标注引用、记成本
            outcome.final = data if isinstance(data, dict) else None
            continue
        try:
            send(event, data)
        except OSError:
            outcome.broken = True
            cancel.set()
            break
    return outcome
