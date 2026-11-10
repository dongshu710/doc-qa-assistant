"""过载时必须「拒绝」，不能「没有回应」。

为什么单独一条：线程槽满的时候，原来的实现是在 accept 阶段阻塞等待。
客户端什么也收不到，30 秒后拿到一个读取超时——运维看到的结论是「服务挂了」，
而真相是「服务忙」。这两种状态的处理方式完全不同（重启 vs 扩容/限流），
所以必须能从客户端区分出来。

预期行为：槽位满 -> 立刻 503 + Retry-After，且不新开线程。
"""
from __future__ import annotations

import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.http_server import BoundedHTTPServer  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802
        if self.path == "/slow":
            time.sleep(1.2)          # 占住唯一的槽位
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):    # 测试输出要保持干净
        pass


def _request(port: int, path: str, timeout: float = 5.0) -> tuple[int, str, dict]:
    """发一个最小 GET，返回 (状态码, 头部原文, body)。"""
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.sendall(
            f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Connection: close\r\n\r\n".encode("ascii")
        )
        chunks = []
        while True:
            piece = sock.recv(4096)
            if not piece:
                break
            chunks.append(piece)
    raw = b"".join(chunks).decode("utf-8", "replace")
    head, _, body = raw.partition("\r\n\r\n")
    status = int(head.split(" ")[1]) if " " in head else 0
    return status, head, body


def main() -> int:
    httpd = BoundedHTTPServer(("127.0.0.1", 0), _Handler, max_workers=1)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    try:
        # 先占住唯一的槽位
        first = threading.Thread(target=_request, args=(port, "/slow"), daemon=True)
        first.start()
        time.sleep(0.25)

        started = time.monotonic()
        status, head, body = _request(port, "/fast")
        elapsed = time.monotonic() - started

        check("槽位满时返回 503", status == 503, f"实际 {status}")
        check("503 立刻返回，不是等到超时", elapsed < 1.0, f"耗时 {elapsed:.3f}s")
        check("带 Retry-After，客户端知道该等多久", "retry-after" in head.lower(), head[:120])
        check("body 是 JSON 且说明是繁忙", '"server_busy"' in body, body[:120])
        check("拒绝计数 +1", httpd.rejected_requests == 1,
              str(httpd.rejected_requests))

        first.join(timeout=3)

        # 槽位释放后必须恢复服务，否则这个修复就成了「一旦忙过就永久 503」
        time.sleep(0.2)
        status2, _, _ = _request(port, "/fast")
        check("槽位释放后恢复正常 200", status2 == 200, f"实际 {status2}")
    finally:
        httpd.shutdown()
        httpd.server_close()

    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("OVERLOAD OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
