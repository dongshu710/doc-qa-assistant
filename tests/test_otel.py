"""OpenTelemetry 导出：协议形状、失败不影响主链路、端到端能收到 span。

为什么要测「失败不影响问答」：导出是可观测性旁路。它一旦能拖慢或打断提问，
用户就会把观测关掉，于是下次出事时又什么都没有。这条比「格式对不对」更重要。
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.otel import TraceExporter, make_exporter  # noqa: E402

FAILED = 0
HOST = "127.0.0.1"


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


class Collector:
    """最小 OTLP/HTTP 接收端：只收 /v1/traces 的 JSON。"""

    def __init__(self) -> None:
        self.batches: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                outer.batches.append(json.loads(body.decode("utf-8")))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer((HOST, 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def spans(self) -> list[dict]:
        out = []
        for batch in self.batches:
            for resource in batch.get("resourceSpans") or []:
                for scope in resource.get("scopeSpans") or []:
                    out.extend(scope.get("spans") or [])
        return out

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def test_shape() -> None:
    print("协议形状")
    collector = Collector()
    exporter = TraceExporter(f"http://{HOST}:{collector.port}", "jiyi-test")
    exporter.emit("rag.ask", time.time_ns() - 5_000_000,
                  {"rag.behavior": "answer", "rag.latency_ms": 5,
                   "rag.api_called": True, "rag.citations": 2})
    sent = exporter.flush_once()
    check("发送 1 条", sent == 1, str(sent))
    spans = collector.spans()
    check("collector 收到 span", len(spans) == 1, str(len(spans)))
    if spans:
        span = spans[0]
        check("span 名字正确", span["name"] == "rag.ask", str(span.get("name")))
        check("traceId 是 32 位十六进制", len(span["traceId"]) == 32,
              str(span.get("traceId")))
        check("spanId 是 16 位十六进制", len(span["spanId"]) == 16,
              str(span.get("spanId")))
        check("时间戳是纳秒字符串",
              span["startTimeUnixNano"].isdigit() and span["endTimeUnixNano"].isdigit(),
              str(span.get("startTimeUnixNano")))
        check("kind 是 SERVER(2)", span.get("kind") == 2, str(span.get("kind")))
        attrs = {item["key"]: item["value"] for item in span.get("attributes") or []}
        check("布尔属性用 boolValue", attrs["rag.api_called"] == {"boolValue": True}, str(attrs))
        check("整数属性用 intValue 且是字符串",
              attrs["rag.latency_ms"] == {"intValue": "5"}, str(attrs))
        check("字符串属性用 stringValue",
              attrs["rag.behavior"] == {"stringValue": "answer"}, str(attrs))
    batch = collector.batches[0]
    resource = batch["resourceSpans"][0]["resource"]["attributes"]
    names = {item["key"]: item["value"] for item in resource}
    check("resource 带 service.name", names.get("service.name") == {"stringValue": "jiyi-test"},
          str(names))
    collector.close()


def test_failure_tolerance() -> None:
    print("失败容忍（观测不能拖垮主链路）")
    # 127.0.0.1:9 通常没人监听：连接会立刻被拒
    exporter = TraceExporter(f"http://{HOST}:9", "jiyi-test",
                             opener=urllib.request.build_opener(
                                 urllib.request.ProxyHandler({})))
    exporter.emit("rag.ask", time.time_ns(), {"a": 1})
    started = time.monotonic()
    sent = exporter.flush_once()
    elapsed = time.monotonic() - started
    check("发送失败返回 0", sent == 0, str(sent))
    check("失败被计数", exporter.stats()["failed"] == 1, str(exporter.stats()))
    check("记录了最后一次错误", bool(exporter.stats()["last_error"]),
          str(exporter.stats().get("last_error")))
    check("没有抛异常、也没有长时间阻塞", elapsed < 10, f"{elapsed:.1f}s")

    # 队列满：丢弃并计数，仍然不抛
    small = TraceExporter(f"http://{HOST}:9", "jiyi-test", max_queue=16)
    for _ in range(200):
        small.emit("rag.ask", time.time_ns(), {})
    stats = small.stats()
    check("队列满时丢弃并计数（不阻塞调用方）",
          stats["dropped"] > 0 and stats["queued"] <= 16, str(stats))


def test_config() -> None:
    print("配置")
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    check("没配端点时不构造导出器（返回 None，不是空实现）", make_exporter() is None)
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "127.0.0.1:4318"
    try:
        make_exporter()
    except ValueError as exc:
        check("端点缺协议时明确报错", "http" in str(exc), str(exc))
    else:
        check("端点缺协议时明确报错", False)
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"http://{HOST}:4318"
    os.environ["OTEL_SERVICE_NAME"] = "my-service"
    exporter = make_exporter()
    check("按环境变量构造", exporter is not None and exporter.service == "my-service",
          str(exporter.service if exporter else None))
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    os.environ.pop("OTEL_SERVICE_NAME", None)


def test_end_to_end() -> None:
    print("端到端：一次问答产生一条 span")
    collector = Collector()
    tmp = tempfile.mkdtemp(prefix="otel_")
    seed = Path(tmp) / "seed"
    seed.mkdir(parents=True)
    (seed / "产品.md").write_text(
        "# 产品\n\n## 要素\n第1条 稳盈系列产品的起购金额为 1 元。\n", encoding="utf-8")
    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(seed),
        "KEYWORD_INDEX": os.path.join(tmp, "kw.json"),
        "RETRIEVAL": "bm25",
        "QUERY_EXPANSION": "off",
        "MIN_SCORE": "0",
        "KB_APPROVAL": "off",
        "KB_WATCH_SECONDS": "0",
        "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://{HOST}:{collector.port}",
        "OTEL_SERVICE_NAME": "jiyi-e2e",
    }
    old = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY", "API_KEYS"):
        os.environ.pop(key, None)

    from src.server import create_server

    httpd, _pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    req = urllib.request.Request(
        base + "/api/ask",
        data=json.dumps({"query": "稳盈系列产品的起购金额是多少"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        answer = json.loads(resp.read().decode("utf-8"))
    check("问答本身正常", "1 元" in (answer.get("answer") or ""),
          (answer.get("answer") or "")[:60])

    # 导出线程每 3 秒冲一次；等它跑一轮
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not collector.spans():
        time.sleep(0.5)
    spans = collector.spans()
    check("collector 收到了这次问答的 span", len(spans) >= 1, str(len(spans)))
    if spans:
        attrs = {item["key"]: item["value"] for item in spans[0].get("attributes") or []}
        check("span 带行为与路径标签",
              "rag.behavior" in attrs and "rag.path" in attrs, str(sorted(attrs)))
        check("span 标了路由", attrs.get("http.route") == {"stringValue": "/api/ask"},
              str(attrs.get("http.route")))

    with urllib.request.urlopen(base + "/api/health", timeout=10) as resp:
        health = json.loads(resp.read().decode("utf-8"))
    otel = health.get("otel") or {}
    check("健康检查报出导出状态",
          otel.get("enabled") is True and otel.get("service") == "jiyi-e2e", str(otel))

    httpd.shutdown()
    httpd.server_close()
    collector.close()
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def main() -> None:
    test_shape()
    test_failure_tolerance()
    test_config()
    test_end_to_end()
    if FAILED:
        print(f"\nOTEL: {FAILED} FAILED")
        raise SystemExit(1)
    print("\nOTEL OK")


if __name__ == "__main__":
    main()
