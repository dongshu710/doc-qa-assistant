"""MCP over HTTP：POST /mcp 的 JSON-RPC 语义必须与 stdio 一致。

为什么单独测：stdio 与 HTTP 是两条传输，但客户端只该看到一套行为。
这里锁住四件事——initialize 能协商版本、通知回 202 且不编造响应、
批量请求按数组返回、GET 明确 405 而不是含糊的 404。
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 本机访问必须绕开系统代理，否则会被代理转成 502
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start(tmp: Path, api_keys: str = ""):
    (tmp / "kb").mkdir()
    (tmp / "kb" / "seed.md").write_text("# 产品\n\n稳盈系列起购金额为 1 元。\n", encoding="utf-8")
    (tmp / "home").mkdir()
    os.environ.update({
        "APP_CONFIG": str(tmp / "app.json"), "NOTE_HOME": str(tmp / "home"),
        "SETUP_DONE": "1", "KB_STORE": "off", "KB_DIR": str(tmp / "kb"),
        "RETRIEVAL": "vector", "EMBEDDING_PROVIDER": "none", "API_KEYS": api_keys,
    })
    from src.server import create_server
    port = free_port()
    httpd, _pipe = create_server("127.0.0.1", port, str(tmp / "kb"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def post(port: int, payload, headers: dict | None = None, raw: bytes | None = None):
    data = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp", data=data, method="POST",
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with OPENER.open(req, timeout=30) as resp:
            body = resp.read()
            return resp.status, (json.loads(body.decode("utf-8")) if body else None)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return exc.code, None


def post_raw(port: int, payload, headers: dict | None = None):
    """POST 并保留原始正文与 Content-Type：SSE 分支不能用 JSON 解析。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp", data=data, method="POST",
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with OPENER.open(req, timeout=30) as resp:
            return resp.status, {"content-type": resp.headers.get("Content-Type") or "",
                                 "body": resp.read().decode("utf-8", "replace")}
    except urllib.error.HTTPError as exc:
        return exc.code, {"content-type": exc.headers.get("Content-Type") or "",
                          "body": exc.read().decode("utf-8", "replace")}


def open_stream(port: int, timeout: float = 10):
    """打开 GET /mcp 的 SSE 流，返回 (响应对象, 首帧文本)。"""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp",
                                 headers={"Accept": "text/event-stream"})
    resp = OPENER.open(req, timeout=timeout)
    return resp, resp.readline().decode("utf-8", "replace")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        httpd, port = start(Path(tmpdir))
        try:
            print("初始化握手")
            code, body = post(port, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                     "params": {"protocolVersion": "2024-11-05",
                                                "capabilities": {},
                                                "clientInfo": {"name": "t", "version": "1"}}})
            check("initialize 返回 200", code == 200, str(code))
            result = (body or {}).get("result") or {}
            check("id 原样回传", (body or {}).get("id") == 1, str(body)[:120])
            check("报出服务名", (result.get("serverInfo") or {}).get("name") == "agent-notes",
                  str(result.get("serverInfo")))
            check("协商协议版本", bool(result.get("protocolVersion")), str(result)[:120])

            print("通知不产生响应")
            code, body = post(port, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            check("通知回 202", code == 202, str(code))
            check("202 无正文", body is None, str(body)[:80])

            print("工具清单与调用")
            code, body = post(port, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            tools = [t.get("name") for t in ((body or {}).get("result") or {}).get("tools") or []]
            check("tools/list 有工具", len(tools) >= 3, str(tools))
            check("含 search_notes", "search_notes" in tools, str(tools))

            code, body = post(port, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                     "params": {"name": "search_notes", "arguments": {"query": "稳盈"}}})
            check("调用工具返回 200", code == 200, str(code))
            check("返回 result 或 error 之一",
                  "result" in (body or {}) or "error" in (body or {}), str(body)[:160])

            code, body = post(port, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                     "params": {"name": "不存在的工具", "arguments": {}}})
            text = json.dumps(body or {}, ensure_ascii=False)
            check("未知工具被拒", "error" in (body or {}) or '"isError"' in text, text[:160])

            print("批量请求")
            code, body = post(port, [
                {"jsonrpc": "2.0", "id": 10, "method": "ping"},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 11, "method": "tools/list"},
            ])
            check("批量返回 200", code == 200, str(code))
            check("批量返回数组", isinstance(body, list), type(body).__name__)
            check("只为有 id 的两条返回", isinstance(body, list) and len(body) == 2, str(body)[:120])
            check("批量 id 保持顺序",
                  isinstance(body, list) and [b.get("id") for b in body] == [10, 11], str(body)[:120])

            print("坏输入")
            code, body = post(port, None, raw=b"{not json")
            check("坏 JSON 回 400", code == 400, str(code))
            check("解析错误码 -32700",
                  ((body or {}).get("error") or {}).get("code") == -32700, str(body)[:120])

            code, body = post(port, {"jsonrpc": "2.0", "id": 12, "method": "没这个方法"})
            check("未知方法 -32601",
                  ((body or {}).get("error") or {}).get("code") == -32601, str(body)[:120])

            print("SSE 下行流（Streamable HTTP）")
            # 严格按规范的客户端会在 Accept 里只要 event-stream，此时必须回 SSE 帧
            code, raw = post_raw(port, {"jsonrpc": "2.0", "id": 20, "method": "ping"},
                                 headers={"Accept": "text/event-stream"})
            check("POST 带 Accept 回 200", code == 200, str(code))
            check("Content-Type 是 text/event-stream",
                  "text/event-stream" in raw["content-type"], raw["content-type"])
            check("正文是 SSE 帧而不是 JSON", raw["body"].startswith("event: message"),
                  raw["body"][:60])
            data_lines = [line for line in raw["body"].splitlines() if line.startswith("data: ")]
            check("恰好一条 data 帧", len(data_lines) == 1, raw["body"][:160])
            sse_payload = json.loads(data_lines[0][6:]) if data_lines else {}
            check("data 里是原 JSON-RPC 响应",
                  sse_payload.get("id") == 20 and "result" in sse_payload, str(sse_payload)[:120])

            print("GET 流可用且会释放名额")
            from src.handlers import base as handler_base
            streams = []
            for _ in range(3):
                try:
                    resp, first = open_stream(port)
                    streams.append(resp)
                    check("GET 流首帧是 connected 注释", first.strip() == ": connected", repr(first))
                    check("GET 流 Content-Type 正确",
                          "text/event-stream" in (resp.headers.get("Content-Type") or ""),
                          str(resp.headers.get("Content-Type")))
                except Exception as exc:  # noqa: BLE001 —— 连不上就是失败，不要吞掉
                    check("GET 流可用", False, f"{type(exc).__name__}: {exc}")
            for resp in streams:
                resp.close()
            for _ in range(60):        # 最多等 3 秒，服务端 detect 到 EOF 会立刻释放
                if handler_base.sse_active() == 0:
                    break
                time.sleep(0.05)
            check("流关闭后名额全部归还", handler_base.sse_active() == 0,
                  str(handler_base.sse_active()))

            print("GET 明确拒绝")
            try:
                with OPENER.open(f"http://127.0.0.1:{port}/mcp", timeout=10) as resp:
                    check("GET 不该成功", False, str(resp.status))
            except urllib.error.HTTPError as exc:
                check("GET 回 405", exc.code == 405, str(exc.code))
                check("带 Allow: POST", "POST" in (exc.headers.get("Allow") or ""),
                      str(exc.headers.get("Allow")))
        finally:
            httpd.shutdown()

    with tempfile.TemporaryDirectory() as tmpdir:
        httpd, port = start(Path(tmpdir), api_keys="sk-http")
        try:
            print("配了 API_KEYS 之后")
            code, _ = post(port, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            check("无 Key 回 401", code == 401, str(code))
            code, body = post(port, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                              headers={"X-API-Key": "sk-http"})
            check("带 Key 放行", code == 200, str(code))
            check("带 Key 能拿到工具", bool(((body or {}).get("result") or {}).get("tools")),
                  str(body)[:120])
        finally:
            httpd.shutdown()

    print(f"\n{'全部通过' if FAILED == 0 else f'{FAILED} 项失败'}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
