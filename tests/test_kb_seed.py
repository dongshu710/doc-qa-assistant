"""空库模板：一键导入内置演示文档。

为什么单独测：这个接口解决的是「新装的人不知道往上传什么」，
它一旦坏了，用户看到的是三个点了没反应的按钮——比没有按钮更糟。
另外它必须幂等：重复点会生成同名覆盖，把「旧内容没了」的告警刷出来，
那等于用引导功能制造一次误报。
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILED = 0
HOST = "127.0.0.1"


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="seed_")
    seed = Path(tmp) / "seed"
    seed.mkdir(parents=True)
    # 只放一份与模板无关的文档：库里有内容（走正常的版本库初始化），
    # 但模板要的几份一份都不在，才能测到「真的导入了」。
    (seed / "无关文档.md").write_text("# 无关\n\n这是一份占位文档。\n", encoding="utf-8")

    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(seed),
        "KEYWORD_INDEX": os.path.join(tmp, "kw.json"),
        "RETRIEVAL": "bm25",
        "QUERY_EXPANSION": "off",
        "KB_APPROVAL": "off",
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

    def post(path: str, body: dict):
        req = urllib.request.Request(
            base + path, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    try:
        print("导入")
        status, body = post("/api/kb/seed", {"template": "policy"})
        check("首次导入 200", status == 200 and body.get("ok"),
              json.dumps(body, ensure_ascii=False)[:200])
        added = body.get("added") or []
        check("导入了模板里的文档", len(added) >= 1, str(added))
        check("没有误报待审批（KB_APPROVAL=off）", body.get("pending") is False,
              str(body.get("pending")))

        print("幂等")
        status, body = post("/api/kb/seed", {"template": "policy"})
        check("重复导入仍然 200", status == 200 and body.get("ok"),
              json.dumps(body, ensure_ascii=False)[:160])
        check("第二次不再新增", not (body.get("added") or []), str(body.get("added")))
        check("第二次全部跳过", len(body.get("skipped") or []) >= 1, str(body.get("skipped")))

        print("参数校验")
        status, body = post("/api/kb/seed", {"template": "nope"})
        check("未知模板 → 400", status == 400, f"{status} {body}")
        status, body = post("/api/kb/seed", {})
        check("缺 template → 400", status == 400, f"{status} {body}")

        print("导入后的列表")
        with urllib.request.urlopen(base + "/api/knowledge", timeout=20) as resp:
            kb = json.loads(resp.read().decode("utf-8"))
        names = [f["name"] for f in kb["files"]]
        check("新文档出现在列表里", any(n in names for n in added), str(names))
        row = next((f for f in kb["files"] if f["name"] in added), None)
        check("列表项带状态字段", row is not None and row.get("status") in
              ("ok", "no_index", "no_page"), str(row))
        check("列表项带 pages", row is not None and isinstance(row.get("pages"), int), str(row))

        print("改名后的页面地址")
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None
        try:
            urllib.request.build_opener(_NoRedirect).open(base + "/files", timeout=10)
            check("/files → 301", False, "居然没跳转")
        except urllib.error.HTTPError as exc:
            check("/files → 301 到 /notes",
                  exc.code == 301 and exc.headers.get("Location") == "/notes",
                  f"{exc.code} {exc.headers.get('Location')}")
        with urllib.request.urlopen(base + "/notes", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        check("/notes 能打开", resp.status == 200 and "pf-grid" in html, str(resp.status))
        check("笔记页标题改过来了", "<title>笔记 ·" in html, html[:80])

    finally:
        httpd.shutdown()
        httpd.server_close()
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    if FAILED:
        print(f"\nKB SEED: {FAILED} FAILED")
        raise SystemExit(1)
    print("\nKB SEED OK")


if __name__ == "__main__":
    main()
