"""API Key 鉴权与 OpenAPI：401 口径、两种携带方式、按 Key 的身份、契约不漂移。"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOST = "127.0.0.1"
_KEYS = ("LLM_API_KEY", "DEEPSEEK_API_KEY")


def _call(port: int, path: str, body: dict | None = None, headers: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    base = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(f"http://{HOST}:{port}{path}", data=data,
                                 headers={**base, **(headers or {})},
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), json.loads(exc.read().decode("utf-8"))


def main() -> None:
    from src.auth import ApiKeyStore

    store = ApiKeyStore("web:sk_test_12345678,sk_abcdefghij")
    assert store.enabled and len(store.keys) == 2
    assert store.identify("sk_test_12345678") == ("web", None)
    name, err = store.identify("sk_abcdefghij")
    assert name and name.startswith("key-") and err is None, (name, err)
    assert store.identify("") == (None, "missing")
    assert store.identify("wrong") == (None, "invalid")
    assert store.mask("sk_test_12345678").endswith("5678")
    print("ApiKeyStore 解析/校验/脱敏 OK")

    tmp = Path(tempfile.mkdtemp(prefix="auth_"))
    seed = tmp / "seed"
    seed.mkdir()
    (seed / "a.md").write_text("# 甲\n\n## 要素\n\n起购金额 1000 元。\n", encoding="utf-8")
    env = {
        "API_KEYS": "web:sk_test_123456,ci:sk_test_abcdef",
        "KB_DIR": str(tmp / "kb"), "KB_SEED_DIR": str(seed),
        "KEYWORD_INDEX": str(tmp / "keywords.json"),
        "RETRIEVAL": "bm25", "QUERY_EXPANSION": "off", "KB_APPROVAL": "off",
        "RATE_LIMIT_BURST": "50",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    for key in _KEYS:
        os.environ.pop(key, None)

    from src.openapi import build_spec
    from src.server import create_server

    # 开放模式：契约里不应出现 security 要求
    open_spec = build_spec("test", {"mode": "open"}, "m", "bm25")
    assert "security" not in open_spec["paths"]["/api/ask"]["post"], "开放模式不应要求 Key"

    httpd, _pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    try:
        status, headers, body = _call(port, "/api/ask", {"query": "起购金额"})
        assert status == 401 and body["error"] == "unauthorized", (status, body)
        assert "bearer" in (headers.get("WWW-Authenticate") or "").lower(), headers
        print("缺少 Key → 401 + WWW-Authenticate OK")

        status, _, body = _call(port, "/api/ask", {"query": "起购金额"},
                                {"X-API-Key": "not-a-key"})
        assert status == 401, (status, body)
        print("错误 Key → 401 OK")

        status, _, body = _call(port, "/api/ask", {"query": "起购金额"},
                                {"Authorization": "Bearer sk_test_123456"})
        assert status == 200 and body.get("answer"), (status, body)
        print("Bearer 正确 Key → 200 OK")

        status, _, body = _call(port, "/api/ask", {"query": "起购金额"},
                                {"X-API-Key": "sk_test_abcdef"})
        assert status == 200 and body.get("request_id"), (status, body)
        print("X-API-Key 正确 Key → 200 OK")

        status, _, health = _call(port, "/api/health")
        assert status == 200 and health["auth"] == {"mode": "key", "keys": 2}, health.get("auth")
        assert "names" not in health["auth"], "健康检查不应暴露调用方名字"
        print("健康检查暴露鉴权模式 OK（不回名字）")

        with urllib.request.urlopen(f"http://{HOST}:{port}/metrics", timeout=10) as resp:
            prom = resp.read().decode("utf-8")
        assert "rag_unauthorized_total" in prom, prom[:200]
        print("未授权计数已进 Prometheus 指标 OK")

        status, _, spec = _call(port, "/openapi.json")
        assert status == 200 and spec["openapi"] == "3.0.3", status
        for path in ("/api/ask", "/api/ask/stream", "/api/feedback", "/api/kb/approve",
                     "/api/knowledge/upload_file"):
            assert path in spec["paths"], path
        ask = spec["paths"]["/api/ask"]["post"]
        assert ask.get("security"), "启用 Key 后契约必须声明 security"
        assert "bearerAuth" in spec["components"]["securitySchemes"]
        assert "apiKeyAuth" in spec["components"]["securitySchemes"]
        assert spec["info"]["x-retrieval"] == "bm25"
        print(f"OpenAPI OK：{len(spec['paths'])} 个路径，鉴权方案 "
              f"{list(spec['components']['securitySchemes'])}")

        print("AUTH & OPENAPI TESTS PASSED")
    finally:
        httpd.shutdown()
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    main()
