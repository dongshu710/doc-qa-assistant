"""两个服务实例共享 Redis：限流与幂等必须跨实例生效。

用法：
    REDIS_URL=redis://127.0.0.1:6379/0 python tests/test_server_redis.py
未找到 Redis 时打印 SKIP 并退出 0（CI 通过 service 容器提供，必须真跑）。
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.redis_client import RedisClient  # noqa: E402
from src.server import create_server  # noqa: E402


def find_redis() -> str:
    for url in (os.getenv("REDIS_URL", ""), "redis://127.0.0.1:6379/0",
                "redis://127.0.0.1:6399/0"):
        if url and RedisClient(url, 1.0).ping():
            return url
    return ""


def post(port: int, path: str, payload: dict, key: str = ""):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8")), dict(exc.headers)


def main() -> None:
    url = find_redis()
    if not url:
        print("SKIP: 未找到 Redis")
        return
    prefix = f"ragtest:{uuid.uuid4().hex[:8]}"
    env = {
        "REDIS_URL": url,
        "REDIS_PREFIX": prefix,
        "RATE_LIMIT_RPS": "0.5",
        "RATE_LIMIT_BURST": "1",
        "KB_STORE": "off",
        "RETRIEVAL": "vector",
        "LLM_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
    }
    with tempfile.TemporaryDirectory(), mock.patch.dict(os.environ, env, clear=False):
        os.environ.pop("LLM_API_KEY", None)
        os.environ.pop("DEEPSEEK_API_KEY", None)
        a, _ = create_server("127.0.0.1", 0, str(ROOT / "data" / "knowledge"))
        b, _ = create_server("127.0.0.1", 0, str(ROOT / "data" / "knowledge"))
        for httpd in (a, b):
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
        pa, pb = a.server_address[1], b.server_address[1]
        try:
            status, first, _ = post(pa, "/api/ask", {"query": "大额存单可以转让吗"}, key="multi-1")
            assert status == 200, (status, first)

            status, denied, _ = post(pb, "/api/ask", {"query": "风险等级怎么划分"}, key="multi-2")
            assert status == 429 and denied.get("retry_after", 0) > 0, (status, denied)
            print("cross-instance rate limit OK (B got 429)")

            # 等令牌回填后再验证跨实例幂等：B 应回放 A 的结果
            time.sleep(2.4)
            status, replay, headers = post(pb, "/api/ask",
                                           {"query": "大额存单可以转让吗"}, key="multi-1")
            assert status == 200, (status, replay)
            assert replay["trace_id"] == first["trace_id"], (first["trace_id"], replay["trace_id"])
            assert headers.get("X-Idempotent-Replay") == "true", headers
            print("cross-instance idempotency OK (B replayed A)")

            with urllib.request.urlopen(f"http://127.0.0.1:{pb}/api/health", timeout=10) as resp:
                health = json.loads(resp.read().decode("utf-8"))
            assert health["guards"]["backend"] == "redis", health["guards"]
            assert health["guards"]["redis_ok"] is True
            print("health reports redis backend OK")
        finally:
            a.shutdown()
            b.shutdown()
            client = RedisClient(url, 1.0)
            keys = client.execute("KEYS", prefix + "*") or []
            if keys:
                client.execute("DEL", *keys)
            client.close()

    print("ALL SERVER REDIS TESTS PASSED")


if __name__ == "__main__":
    main()
