"""启动顺序：先占端口、再建索引。

为什么单独测：这条改的是「请求什么时候能被接受」。写错的表现不是异常，而是
用户那边几分钟的 `ECONNREFUSED`（服务其实在正常加载），或者更糟——
建库没完成时返回一个「检索结果为空」的答案，用户看到「无法找到答案」。
后者是错答案，前者只是慢，两者必须能区分，所以这里逐条钉住：

1. 端口绑定后、索引未就绪时：`/api/health` 立刻 200 + `state=starting`；
2. 同一时刻其它接口 503 + `Retry-After`，**不能**是 200 空结果；
3. 交棒之后同一个端口就是真服务：health 不再说 starting，ask 能正常答。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.handlers.app import build_app  # noqa: E402
from src.http_server import BoundedHTTPServer, StartingHandler  # noqa: E402

HOST = "127.0.0.1"
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def request(port: int, path: str, payload: dict | None = None):
    """返回 (状态码, 响应头, 正文)。不走系统代理：127.0.0.1 走代理会 502。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"http://{HOST}:{port}{path}", data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data else "GET")
    try:
        with opener.open(req, timeout=20) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read().decode("utf-8", "replace")


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="startup_")
    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(ROOT / "data" / "demo"),
        "KB_APPROVAL": "off",
        "KEYWORD_INDEX": os.path.join(tmp, "kw.json"),
        "RETRIEVAL": "bm25",
        "QUERY_EXPANSION": "off",
        "MIN_SCORE": "0",
        "KEYWORD_MODE": "off",
        "LOG_DIR": os.path.join(tmp, "logs"),
        "RAW_DIR": os.path.join(tmp, "raw"),
        "ARTIFACTS_DIR": os.path.join(tmp, "artifacts"),
        "SETUP_DONE": "1",
        "APP_CONFIG": os.path.join(tmp, "app.json"),
        "EMBEDDING_PROVIDER": "none",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY"):
        os.environ.pop(key, None)

    httpd = None
    try:
        # ---- 阶段一：只绑端口，用启动期应答器 ----
        httpd = BoundedHTTPServer((HOST, 0), StartingHandler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, name="startup-answers",
                         daemon=True).start()

        status, headers, body = request(port, "/api/health")
        started = json.loads(body) if body.strip().startswith("{") else {}
        check("启动期端口已可连（不是 ECONNREFUSED）", status == 200, f"{status} {body[:120]}")
        check("启动期 health 明确报 starting", started.get("state") == "starting", body[:160])

        status, headers, body = request(port, "/api/ask", {"query": "我几点起床"})
        check("启动期 ask 返 503 而不是空结果", status == 503, f"{status} {body[:160]}")
        check("启动期 503 带 Retry-After", bool(headers.get("Retry-After")), str(headers)[:160])
        check("启动期 503 说明原因", "starting" in body, body[:160])

        # ---- 阶段二：建索引（慢活），然后交棒 ----
        httpd, pipe = build_app(HOST, port, server=httpd)
        check("交棒：处理器已换成真 Handler",
              getattr(httpd, "handler_ready", False) is True,
              str(getattr(httpd, "RequestHandlerClass", None)))

        status, _headers, body = request(port, "/api/health")
        health = json.loads(body) if body.strip().startswith("{") else {}
        check("交棒后 health 不再是 starting", health.get("state") != "starting", body[:200])
        check("交棒后 health 带真实数据（版本或块数）",
              bool(health.get("version") or health.get("chunks") is not None), body[:200])

        # 用 demo 语料里确实有的问题：问库外的内容本来就会答「无法找到答案」，
        # 拿它当断言等于把「语料没有」误判成「启动顺序有问题」。
        status, _headers, body = request(port, "/api/ask", {"query": "我几点起床"})
        answered = {}
        try:
            answered = json.loads(body)
        except json.JSONDecodeError:
            pass
        check("交棒后 ask 能正常作答", status == 200 and bool(answered.get("answer")),
              f"{status} {body[:200]}")
        check("答案不因启动期而过早返回「无法找到答案」",
              answered.get("answer") != "无法找到答案。", str(answered.get("answer"))[:120])
        print(f"       语料块数 {len(pipe.chunks)}")
    finally:
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("STARTUP ORDER OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
