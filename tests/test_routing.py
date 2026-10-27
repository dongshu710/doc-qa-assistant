"""路由鉴权表：等级解析对不对、真服务上拦不拦、每个 do_* 有没有过闸。

为什么要单独测这张表：它的价值就是「不依赖人记得加检查」。
所以既要断言表本身（最长前缀、默认收紧），也要断言分发函数确实调了 `_guard`——
否则表写得再对，绕过它一样等于没有。
"""
import http.client
import json
import re
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import routing  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def call(port: int, method: str, path: str, body: dict | None = None,
         headers: dict | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    payload = None
    head = {"Accept": "application/json"}
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        head["Content-Type"] = "application/json"
    head.update(headers or {})
    try:
        conn.request(method, path, body=payload, headers=head)
        resp = conn.getresponse()
        raw = resp.read()
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            data = {"_raw": raw[:200].decode("utf-8", "replace")}
        return resp.status, data
    finally:
        conn.close()


def start(tmp: Path, extra: dict):
    import os
    import socket

    (tmp / "kb").mkdir()
    (tmp / "kb" / "seed.md").write_text("# 产品\n\n稳盈系列起购金额为 1 元。\n", encoding="utf-8")
    (tmp / "home").mkdir()
    env = {
        "APP_CONFIG": str(tmp / "app.json"), "NOTE_HOME": str(tmp / "home"),
        "SETUP_DONE": "1", "KB_STORE": "off", "KB_DIR": str(tmp / "kb"),
        "RETRIEVAL": "vector", "EMBEDDING_PROVIDER": "none", "API_KEYS": "",
        "ADMIN_TOKEN": "",
    }
    env.update(extra)
    os.environ.update(env)
    from src.server import create_server
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    httpd, _pipe = create_server("127.0.0.1", port, str(tmp / "kb"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def test_table() -> None:
    print("等级解析")
    cases = [
        ("/api/settings", routing.OPEN),
        ("/api/settings/storage/clean", routing.OPEN),
        ("/api/health", routing.OPEN),
        ("/api/update/check", routing.OPEN),
        ("/tools.json", routing.OPEN),
        ("/ask", routing.OPEN),
        ("/kb", routing.OPEN),
        ("/metrics", routing.ADMIN),
        ("/api/audit", routing.ADMIN),
        ("/api/admin/config", routing.ADMIN),
        ("/api/kb/approve", routing.ADMIN),
        ("/api/kb/reject", routing.ADMIN),
        ("/api/kb/versions", routing.API),
        ("/api/knowledge/upload", routing.API),
        ("/api/source", routing.API),
        ("/api/notes", routing.API),
        ("/api/threads/abc", routing.API),
        ("/api/files/raw", routing.API),
        ("/api/brand-new-endpoint", routing.API),   # 未登记 → 默认收紧
    ]
    for path, want in cases:
        got = routing.level_for(path)
        check(f"{path} → {want}", got == want, f"实际 {got}")

    prefixes = [item["prefix"] for item in routing.describe()]
    check("前缀没有重复", len(prefixes) == len(set(prefixes)), str(prefixes))

    print("最长前缀优先")
    check("/api/kb/approve 不被 /api/kb 覆盖",
          routing.level_for("/api/kb/approve") == routing.ADMIN)
    check("/api/kb/rollback_doc 不被 /api/kb 覆盖",
          routing.level_for("/api/kb/rollback_doc") == routing.ADMIN)
    check("前缀只按路径段匹配", routing.level_for("/api/settingsX") == routing.API,
          routing.level_for("/api/settingsX"))


def test_dispatch_guard() -> None:
    print("分发函数必须过闸")
    text = (ROOT / "src" / "server.py").read_text(encoding="utf-8")
    for verb in ("do_GET", "do_POST", "do_PUT", "do_PATCH", "do_DELETE", "do_OPTIONS"):
        match = re.search(rf"def {verb}\(self\).*?(?=\n        def )", text, re.S)
        check(f"{verb} 存在", bool(match), verb)
        if not match:
            continue
        check(f"{verb} 第一句就是 _guard",
              re.search(r"if self\._guard\(", match.group(0)) is not None,
              match.group(0)[:60].replace("\n", " "))


def test_enforcement() -> None:
    print("配了 Key 之后的读接口")
    with tempfile.TemporaryDirectory() as tmpdir:
        httpd, port = start(Path(tmpdir), {"API_KEYS": "web:sk_route_123456"})
        try:
            code, _ = call(port, "GET", "/api/source?doc=seed&chunk=0")
            check("原文没 Key → 401", code == 401, str(code))
            code, _ = call(port, "GET", "/api/trace?limit=1")
            check("提问记录没 Key → 401", code == 401, str(code))
            code, _ = call(port, "GET", "/api/notes")
            check("笔记没 Key → 401", code == 401, str(code))
            code, _ = call(port, "POST", "/api/knowledge/upload",
                           body={"name": "x.md", "content": "# x\n"})
            check("上传没 Key → 401", code == 401, str(code))
            code, _ = call(port, "GET", "/api/health")
            check("健康检查保持开放", code == 200, str(code))
            code, _ = call(port, "GET", "/api/settings")
            check("设置保持开放", code == 200, str(code))
            auth = {"Authorization": "Bearer sk_route_123456"}
            code, _ = call(port, "GET", "/api/notes", headers=auth)
            check("带 Key 读笔记 → 200", code == 200, str(code))
            code, body = call(port, "POST", "/api/knowledge/upload",
                              body={"name": "ok.md", "content": "# 正常\n"}, headers=auth)
            check("带 Key 上传 → 200", code == 200, str(code)[:80] + str(body)[:80])
        finally:
            httpd.shutdown()
            httpd.server_close()

    print("配了管理员令牌之后")
    with tempfile.TemporaryDirectory() as tmpdir:
        httpd, port = start(Path(tmpdir), {"API_KEYS": "", "ADMIN_TOKEN": "adm-xyz"})
        try:
            code, _ = call(port, "GET", "/metrics")
            check("指标没令牌 → 403", code == 403, str(code))
            code, _ = call(port, "GET", "/metrics", headers={"X-Admin-Token": "adm-xyz"})
            check("带令牌读指标 → 200", code == 200, str(code))
            code, _ = call(port, "GET", "/api/audit")
            check("审计没令牌 → 403", code == 403, str(code))
            code, _ = call(port, "GET", "/api/health")
            check("健康检查不受影响", code == 200, str(code))
        finally:
            httpd.shutdown()
            httpd.server_close()


def main() -> int:
    test_table()
    test_dispatch_guard()
    test_enforcement()
    print()
    print("全部通过" if not FAILED else f"{FAILED} 项失败")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
