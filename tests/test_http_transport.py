"""HTTP 传输层：HTTP/1.1 保活、gzip、ETag/304、HEAD、API 不缓存。

这些是「页面加载慢」的直接原因，但很难靠肉眼发现，所以用裸 socket + 响应头断言守住。
"""
import gzip
import json
import os
import socket
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"


def raw_request(port: int, path: str, extra: str = "") -> tuple[str, dict, bytes]:
    """发一个 HTTP/1.1 请求，返回 (状态行, 头字典, 主体)。"""
    with socket.create_connection((HOST, port), timeout=10) as sock:
        request = (f"GET {path} HTTP/1.1\r\nHost: {HOST}\r\n"
                   f"Connection: keep-alive\r\n{extra}\r\n")
        sock.sendall(request.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        while len(rest) < length:
            chunk = sock.recv(65536)
            if not chunk:
                break
            rest += chunk
        return lines[0], headers, rest[:length]


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="http_perf_")
    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(ROOT / "data" / "demo"),
        "KEYWORD_INDEX": os.path.join(tmp, "keywords.json"),
        "RETRIEVAL": "bm25",
        "QUERY_EXPANSION": "off",
        "KB_APPROVAL": "off",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY"):
        os.environ.pop(key, None)

    from src.server import create_server

    httpd, _pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    try:
        # ---------- 1) 协议与定长 ----------
        status, headers, body = raw_request(port, "/ask")
        assert status.startswith("HTTP/1.1 200"), status
        assert headers.get("content-length") == str(len(body)), headers
        assert headers.get("etag", "").startswith('W/"'), headers
        assert headers.get("cache-control") == "no-cache", headers
        identity_len = len(body)
        print(f"HTTP/1.1 定长响应 OK：/ask {identity_len} B")

        # ---------- 2) 同一连接复用（keep-alive）----------
        with socket.create_connection((HOST, port), timeout=10) as sock:
            for _ in range(2):
                sock.sendall(f"GET /api/health HTTP/1.1\r\nHost: {HOST}\r\nConnection: keep-alive\r\n\r\n".encode())
                buf = b""
                while b"\r\n\r\n" not in buf:
                    buf += sock.recv(4096)
                head, _, rest = buf.partition(b"\r\n\r\n")
                length = 0
                for line in head.decode("latin-1").split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        length = int(line.split(":", 1)[1])
                while len(rest) < length:
                    rest += sock.recv(65536)
                assert head.startswith(b"HTTP/1.1 200"), head[:40]
        print("keep-alive OK：同一连接两次请求")

        # ---------- 3) gzip ----------
        status, headers, packed = raw_request(port, "/ask", "Accept-Encoding: gzip\r\n")
        assert headers.get("content-encoding") == "gzip", headers
        assert headers.get("vary", "").lower() == "accept-encoding", headers
        plain = gzip.decompress(packed)
        assert len(plain) == identity_len, (len(plain), identity_len)
        ratio = 1 - len(packed) / len(plain)
        print(f"gzip OK：{len(plain)} B → {len(packed)} B（省 {ratio:.0%}）")
        assert ratio > 0.5, "HTML 压缩率异常，检查是否漏压"

        # ---------- 4) ETag / 304 ----------
        status, headers, _ = raw_request(port, "/ask")
        etag = headers["etag"]
        status304, headers304, body304 = raw_request(port, "/ask", f"If-None-Match: {etag}\r\n")
        assert status304.startswith("HTTP/1.1 304"), status304
        assert body304 == b"", body304
        assert headers304.get("etag") == etag
        print("ETag/304 OK：重复访问 0 字节正文")

        # ---------- 5) HEAD ----------
        with socket.create_connection((HOST, port), timeout=10) as sock:
            sock.sendall(f"HEAD /ask HTTP/1.1\r\nHost: {HOST}\r\nConnection: close\r\n\r\n".encode())
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
            head = buf.partition(b"\r\n\r\n")[0].decode("latin-1")
            assert " 200 " in head.split("\r\n")[0], head
            assert "content-length" in head.lower(), head
            rest = buf.partition(b"\r\n\r\n")[2]
            assert rest == b"", "HEAD 不应返回响应体"
        print("HEAD OK：200 + 长度头，无正文")

        # ---------- 6) JSON 接口不缓存 ----------
        req = urllib.request.Request(f"http://{HOST}:{port}/api/health")
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.headers.get("Cache-Control") == "no-store", dict(resp.headers)
            json.loads(resp.read().decode("utf-8"))
        print("JSON no-store OK")

        # ---------- 7) SSE 仍然可用（不能被通用 _send 破坏）----------
        payload = json.dumps({"query": "我有什么爱好", "session_id": "http-test"}).encode("utf-8")
        req = urllib.request.Request(
            f"http://{HOST}:{port}/api/ask/stream", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            assert "text/event-stream" in resp.headers.get("Content-Type", ""), dict(resp.headers)
            text = resp.read().decode("utf-8")
        assert "event: final" in text, text[:200]
        print("SSE OK：流式接口未被压缩/定长逻辑影响")

        print("HTTP TRANSPORT OK")
    finally:
        httpd.shutdown()
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    main()
