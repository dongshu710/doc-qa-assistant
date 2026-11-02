"""协议层语义：错误体形状、方法不匹配、参数校验、上传覆盖告警。

为什么要单独一个脚本：这些都不是「功能对不对」，而是「出问题时说不说得清」。
1.27.0 一次用户视角测试里攒出 5 种错误体形状、方法错报 404、缺 query 报 200 澄清、
非法枚举返回空列表——单测各自都过，因为没人把「错误路径」当契约来测。

运行：python tests/test_http_semantics.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"
CODE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
FAILED: list[str] = []


def check(name: str, ok: bool, detail="") -> None:
    if ok:
        print(f"  ok   {name}")
        return
    FAILED.append(f"{name} → {detail}")
    print(f"  FAIL {name} → {detail}")


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="http_sem_")
    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(ROOT / "data" / "knowledge"),
        "KEYWORD_INDEX": os.path.join(tmp, "keywords.json"),
        "RETRIEVAL": "vector",
        "QUERY_EXPANSION": "off",
        "KB_APPROVAL": "off",
        "NOTE_HOME": os.path.join(tmp, "home"),
        "SETUP_DONE": "1",
        "APP_CONFIG": os.path.join(tmp, "app.json"),
        "EMBEDDING_PROVIDER": "none",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY"):
        os.environ.pop(key, None)

    from src.server import create_server

    httpd, _pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(method, path, payload=None, headers=None):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        head = {"Content-Type": "application/json"}
        if headers:
            head.update(headers)
        req = urllib.request.Request(base + path, data=data, headers=head, method=method)
        try:
            with opener.open(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8")), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(raw), dict(exc.headers)
            except ValueError:
                return exc.code, {"__raw__": raw}, dict(exc.headers)

    print("[1] 错误体形状统一")
    bad_bodies = [
        ("GET", "/api/definitely-not-here", None),
        ("PUT", "/api/notes", {}),
        ("POST", "/api/ask", {}),
        ("POST", "/api/ask", {"query": 123}),
        ("GET", "/api/notes?kind=%E4%B9%B1%E5%86%99", None),
        ("GET", "/api/notes?since=2026-13-45", None),
    ]
    for method, path, payload in bad_bodies:
        status, body, _h = call(method, path, payload)
        shaped = (body.get("ok") is False and isinstance(body.get("error"), str)
                  and CODE_RE.match(body["error"] or "") and bool(body.get("message")))
        check(f"{method} {path} → {status} 形状合规",
              status >= 400 and shaped, body)

    print("[2] 方法不匹配回 405 而不是 404")
    status, body, headers = call("PUT", "/api/notes", {})
    check("PUT /api/notes → 405", status == 405 and body.get("error") == "method_not_allowed",
          f"{status} {body}")
    check("405 带 Allow 头", "allow" in {k.lower() for k in headers}, headers)
    status, _b, _h = call("GET", "/api/ask")
    check("GET /api/ask → 405（原来 404）", status == 405, status)
    status, body, _h = call("GET", "/api/nope")
    check("未登记路径仍是 404", status == 404 and body.get("error") == "not_found", body)

    print("[3] 提问参数校验")
    status, body, _h = call("POST", "/api/ask", {"question": "年假多少天"})
    check("字段名写错 → 400（不再 200 澄清）", status == 400, f"{status} {body}")
    status, body, _h = call("POST", "/api/ask", {"query": 123})
    check("query 非字符串 → 400", status == 400 and "字符串" in body.get("message", ""), body)
    status, body, _h = call("POST", "/api/ask", {"query": ""})
    check("空串仍是澄清（聊天语义）", status == 200 and body.get("behavior") == "ask_clarify",
          body.get("behavior"))

    print("[4] 笔记 id 解码")
    status, body, _h = call("GET", "/api/notes/" + urllib.parse.quote("不存在的笔记"))
    check("错误信息里不含 %XX", status == 400 and "%" not in body.get("message", ""),
          body.get("message"))

    print("[5] 同名上传要带回 warnings")
    md = "# 覆盖测试文档\n\n## 条款\n首版内容：起购金额 1 万元。\n"
    status, first, _h = call("POST", "/api/knowledge/upload",
                             {"name": "覆盖测试.md", "content": md})
    check("首次上传无 warnings", status == 200 and not first.get("warnings"), first.get("warnings"))
    md2 = "# 覆盖测试文档\n\n## 条款\n第二版内容：起购金额 2 万元。\n"
    status, second, _h = call("POST", "/api/knowledge/upload",
                              {"name": "覆盖测试.md", "content": md2})
    warns = second.get("warnings") or []
    check("覆盖同名文档时带 warnings", status == 200 and any("覆盖" in w for w in warns), second)
    check("响应里有可回滚的提示语义", any("覆盖测试.md" in w for w in warns), warns)

    print("[6] 引用能回到原文（回归）")
    status, ans, _h = call("POST", "/api/ask", {"query": "大额存单起存金额是多少"})
    cites = ans.get("citations") or []
    ok_all = bool(cites)
    for c in cites:
        qs = "?doc=" + urllib.parse.quote(str(c["doc_id"])) + "&chunk=" + str(c["chunk_index"])
        st, src, _hh = call("GET", "/api/source" + qs)
        if st != 200 or not (src.get("text") or "").strip():
            ok_all = False
    check(f"{len(cites)} 条引用都能打开原文", ok_all, cites)

    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    httpd.shutdown()

    print()
    if FAILED:
        for item in FAILED:
            print("  ✗", item)
        raise SystemExit(1)
    print("协议层语义测试通过")


if __name__ == "__main__":
    main()
