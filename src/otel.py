"""OpenTelemetry 导出（OTLP/HTTP + JSON），零第三方依赖。

为什么自己实现而不是装 `opentelemetry-sdk`：
- 那套 SDK 会带进 `protobuf`、`grpc` 等一串依赖，违背本项目「零依赖」的硬约束；
- 我们需要的东西很少：一次问答一条 span，字段固定。OTLP/HTTP 的 **JSON** 编码
  是协议里明确定义的（spec 的 `otlp-http` 部分），用标准库就能发。

边界（写清楚）：
- 只导出 traces，不导出 metrics 与 logs。指标已经有 Prometheus 文本端点，
  再导一份只会让两处口径打架。
- 不支持采样率、批量压缩（gzip）、gRPC。批量按「攒到 N 条或 T 秒」发送，
  这是本地单实例够用的最小形态；真要上量应该让 collector 做批处理。
- 发送失败只做有限重试，之后丢弃并计数。**绝不能因为导出失败影响问答**——
  可观测性是旁路，不是主链路。

配置：
    OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318   # collector 的 HTTP 端口
    OTEL_SERVICE_NAME=jiyi（默认）
    OTEL_TRACE_MAX_QUEUE=512（默认，满了丢弃并计数）
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
import uuid

MAX_ATTRIBUTES = 32
FLUSH_INTERVAL_S = 3.0
REQUEST_TIMEOUT_S = 3.0
DEFAULT_QUEUE = 512


def _attr(key: str, value) -> dict:
    """OTLP 的 attribute 是 tagged union：值类型必须显式说明。"""
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)[:400]}}


def _hex(count: int) -> str:
    """traceId 16 字节 / spanId 8 字节，十六进制小写——OTLP/JSON 要求字符串形式。"""
    return uuid.uuid4().hex[:count]


class TraceExporter:
    """后台线程按批发送 span 到 OTLP/HTTP collector。"""

    def __init__(self, endpoint: str, service: str = "jiyi",
                 max_queue: int = DEFAULT_QUEUE, opener=None):
        self.endpoint = endpoint.rstrip("/")
        self.service = service
        self.url = self.endpoint + "/v1/traces"
        self._queue: queue.Queue = queue.Queue(maxsize=max(16, max_queue))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.sent = 0
        self.dropped = 0
        self.failed = 0
        self.last_error = ""
        # 走不走系统代理：与客户端一致的教训——本机代理会把回环请求也劫走。
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}))

    # ---- 生命周期 ----
    def start(self) -> "TraceExporter":
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="otel-export", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    # ---- 入口 ----
    def emit(self, name: str, started_ns: int, attributes: dict) -> None:
        """把一条 span 放进队列。满了就丢，并让 dropped 涨上去。

        丢弃而不是阻塞：问答线程绝不能等导出——collector 挂了不该让提问变慢。
        """
        span = self._span(name, started_ns, time.time_ns(), attributes)
        try:
            self._queue.put_nowait(span)
        except queue.Full:
            with self._lock:
                self.dropped += 1

    def _span(self, name: str, start_ns: int, end_ns: int, attributes: dict) -> dict:
        attrs = [_attr(key, value) for key, value in list(attributes.items())[:MAX_ATTRIBUTES]]
        return {
            "traceId": _hex(32),
            "spanId": _hex(16),
            "name": name,
            # kind=2 是 SPAN_KIND_SERVER：这是服务端收到请求后处理的那一段
            "kind": 2,
            "startTimeUnixNano": str(int(start_ns)),
            "endTimeUnixNano": str(int(end_ns)),
            "attributes": attrs,
            "status": {"code": 1},        # STATUS_CODE_OK
        }

    def _payload(self, spans: list[dict]) -> dict:
        return {"resourceSpans": [{
            "resource": {"attributes": [_attr("service.name", self.service)]},
            "scopeSpans": [{"scope": {"name": "jiyi.rag", "version": "1"},
                            "spans": spans}],
        }]}

    def _run(self) -> None:
        while not self._stop.wait(FLUSH_INTERVAL_S):
            self.flush_once()

    def flush_once(self) -> int:
        """把队列里现有的 span 发出去一次，返回成功发送的条数。"""
        batch: list[dict] = []
        while len(batch) < 64:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if not batch:
            return 0
        body = json.dumps(self._payload(batch), ensure_ascii=False).encode("utf-8")
        # 有限重试：collector 重启通常几秒内回来，重试 2 次足够；
        # 再多会让队列堆积，反而把后面的正常 span 一起拖丢。
        for attempt in range(3):
            try:
                request = urllib.request.Request(
                    self.url, data=body, method="POST",
                    headers={"Content-Type": "application/json"})
                with self._opener.open(request, timeout=REQUEST_TIMEOUT_S) as response:
                    response.read()
                with self._lock:
                    self.sent += len(batch)
                    self.last_error = ""
                return len(batch)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                self.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                if attempt < 2:
                    time.sleep(0.2 * (attempt + 1))
        with self._lock:
            self.failed += len(batch)
        return 0

    def stats(self) -> dict:
        with self._lock:
            return {"enabled": True, "endpoint": self.endpoint, "service": self.service,
                    "queued": self._queue.qsize(), "sent": self.sent,
                    "failed": self.failed, "dropped": self.dropped,
                    "last_error": self.last_error}


def make_exporter(settings=None) -> TraceExporter | None:
    """按配置构造；没配就返回 None（而不是一个空实现），调用方据此跳过整条路径。"""
    endpoint = (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    if not endpoint:
        return None
    if not endpoint.startswith(("http://", "https://")):
        # 配错的端点如果静默忽略，用户会以为「已经接上了」
        raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT 必须是 http:// 或 https:// 开头")
    service = (os.environ.get("OTEL_SERVICE_NAME") or "jiyi").strip()[:64]
    try:
        max_queue = int(os.environ.get("OTEL_TRACE_MAX_QUEUE", str(DEFAULT_QUEUE)))
    except (TypeError, ValueError):
        max_queue = DEFAULT_QUEUE
    return TraceExporter(endpoint, service, max_queue)
