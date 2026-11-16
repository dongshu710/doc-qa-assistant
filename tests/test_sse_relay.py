"""SSE 中继：断连即取消、总时长上限、心跳、异常回传。

为什么单独测这一层：`relay` 是两条流式（内部事件流与 OpenAI chunk）共用的骨架，
它错一个分支就是「客户端走了、模型还在烧 token」或者「超时了但连接不关」——
两种都不报错，只在账单和线程数上体现。这里用假流把四种结局逐个走一遍，
不起服务、不依赖任何网络。
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.handlers import sse  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


class FakeStream:
    """可控的假生成器：记录 close() 有没有被调用——这是「取消真的生效」的唯一证据。"""

    def __init__(self, items, delay: float = 0.02, on_close=None):
        self.items = items
        self.delay = delay
        self.closed = False
        self._on_close = on_close

    def __iter__(self):
        for item in self.items:
            time.sleep(self.delay)
            yield item

    def close(self) -> None:
        self.closed = True
        if self._on_close:
            self._on_close()


def case_normal() -> None:
    print("正常结束")
    sent: list[tuple[str, object]] = []
    cancel = threading.Event()
    stream = FakeStream([("delta", "a"), ("delta", "b"), ("final", {"answer": "ab"})])
    outcome = sse.relay(factory=lambda: stream, send=lambda e, d: sent.append((e, d)),
                        cancel=cancel, max_seconds=5, heartbeat_s=0.5)
    check("返回 final 且没有错误", outcome.final == {"answer": "ab"} and not outcome.error
          and not outcome.timed_out and not outcome.broken, str(outcome))
    check("增量按顺序发出了", [e for e, _ in sent] == ["delta", "delta"], str(sent))
    check("final 不由 relay 发（调用方要记账后再发）",
          all(e != "final" for e, _ in sent), str(sent))
    check("正常结束也会关闭生成器", stream.closed, "close 未被调用")


def case_broken() -> None:
    print("客户端断开")
    cancel = threading.Event()
    holder = {}

    def on_close() -> None:
        holder["closed_at"] = time.monotonic()

    stream = FakeStream([("delta", "x")] * 50, delay=0.03, on_close=on_close)
    sent: list[str] = []

    def send(event, data) -> None:
        sent.append(str(data))
        if len(sent) >= 2:
            raise ConnectionResetError("客户端走了")

    began = time.monotonic()
    outcome = sse.relay(factory=lambda: stream, send=send, cancel=cancel,
                        max_seconds=10, heartbeat_s=1)
    elapsed = time.monotonic() - began
    check("断连被识别为 broken", outcome.broken is True, str(outcome))
    check("断连立即取消（cancel 置位）", cancel.is_set(), str(cancel.is_set()))
    check("断连后很快返回（不等满 50 个块）", elapsed < 2.0, f"{elapsed:.2f}s")
    # close 在 worker 线程的 finally 里，回来后再给它一点时间
    for _ in range(50):
        if holder.get("closed_at"):
            break
        time.sleep(0.02)
    check("断连后生成器被关闭（上游请求会中断）", bool(holder.get("closed_at")),
          f"{elapsed:.2f}s 内未关闭")
    if holder.get("closed_at"):
        check("关闭发生在断连后 2 秒内",
              holder["closed_at"] - began < 2.0, f"{holder['closed_at'] - began:.2f}s")


def case_timeout() -> None:
    print("总时长上限")
    cancel = threading.Event()
    stream = FakeStream([("delta", "x")] * 100, delay=0.05)   # 理论要 5 秒
    began = time.monotonic()
    outcome = sse.relay(factory=lambda: stream, send=lambda e, d: None,
                        cancel=cancel, max_seconds=0.3, heartbeat_s=0.1)
    elapsed = time.monotonic() - began
    check("超时被标记", outcome.timed_out is True, str(outcome))
    check("超时也置位取消", cancel.is_set(), str(cancel.is_set()))
    # 上限 0.3s：允许一个心跳的余量，但不许接近 5 秒
    check("在预算附近就掐断（不是等流结束）", elapsed < 1.5, f"{elapsed:.2f}s")


def case_error() -> None:
    print("生成线程抛错")
    def factory():
        raise RuntimeError("模型 500")
    outcome = sse.relay(factory=factory, send=lambda e, d: None,
                        cancel=threading.Event(), max_seconds=5, heartbeat_s=0.2)
    check("异常回传给调用方（不吞）", "模型 500" in outcome.error, str(outcome))
    check("异常路径不算超时/断连", not outcome.timed_out and not outcome.broken, str(outcome))


def case_heartbeat() -> None:
    print("空闲心跳")
    beats: list[float] = []
    stream = FakeStream([("delta", "x")], delay=0.5)
    outcome = sse.relay(factory=lambda: stream, send=lambda e, d: None,
                        cancel=threading.Event(),
                        heartbeat=lambda: beats.append(time.monotonic()),
                        max_seconds=5, heartbeat_s=0.1)
    check("空闲期发了心跳", len(beats) >= 2, f"{len(beats)} 次")
    check("有心跳也不影响正常结束", outcome.final is None and not outcome.error, str(outcome))


def main() -> int:
    case_normal()
    case_broken()
    case_timeout()
    case_error()
    case_heartbeat()
    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("SSE RELAY OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
