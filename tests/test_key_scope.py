"""API Key 作用域：只读 Key 能读、能问，但不能写。

为什么这条重要：没有作用域时，给 MCP 客户端或仪表盘只能发全权 Key，
一次泄露就是「整库可改可删」。有了 `:ro` 后缀，同一套接口可以按用途区分。

测试重点不是「能拒」，而是**拒得准**：
- 该放行的读语义 POST（提问、检索调试）不能一并挡掉；
- 只读 Key 收到的错误必须是 `read_only_key` 而不是 `unauthorized`，
  否则用户会去反复核对一个本来就对的密钥。
"""
import base64
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

from src.auth import ApiKeyStore  # noqa: E402

FAILED = 0
HOST = "127.0.0.1"
RO_KEY = "ro-key-123456"
RW_KEY = "rw-key-123456"
ADMIN_KEY = "adm-key-123456"


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def test_parse() -> None:
    print("配置解析（含向后兼容）")
    store = ApiKeyStore(f"web:{RW_KEY},mcp:{RO_KEY}:ro,adm:{ADMIN_KEY}:admin,plainkey")
    check("两段式仍是 名字:密钥",
          store.identify_scope(RW_KEY) == ("web", "rw", None), str(store.identify_scope(RW_KEY)))
    check("三段式读出只读", store.identify_scope(RO_KEY) == ("mcp", "ro", None),
          str(store.identify_scope(RO_KEY)))
    check("三段式读出管理员", store.identify_scope(ADMIN_KEY) == ("adm", "admin", None),
          str(store.identify_scope(ADMIN_KEY)))
    check("不带名字的 Key 仍可用", store.identify_scope("plainkey")[1] == "rw",
          str(store.identify_scope("plainkey")))
    check("无效 Key 的作用域是空串（不是 rw）", store.identify_scope("nope") == (None, "", "invalid"),
          str(store.identify_scope("nope")))
    check("describe 报出只读 Key 数量", store.describe().get("read_only") == 1,
          str(store.describe()))

    # 密钥里带冒号的老写法不能被误判成作用域
    tricky = ApiKeyStore("name:sk:with:colons")
    check("多段但末段不是作用域时按原样当密钥",
          tricky.identify_scope("sk:with:colons")[0] == "name",
          str(tricky.identify_scope("sk:with:colons")))


def main() -> None:
    test_parse()

    tmp = tempfile.mkdtemp(prefix="scope_")
    seed = Path(tmp) / "seed"
    seed.mkdir(parents=True)
    (seed / "产品.md").write_text(
        "# 产品\n\n## 要素\n第1条 稳盈系列产品的起购金额为 1 元。\n", encoding="utf-8")
    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(seed),
        "KEYWORD_INDEX": os.path.join(tmp, "kw.json"),
        "RAW_DIR": os.path.join(tmp, "raw"),
        "RETRIEVAL": "bm25",
        "QUERY_EXPANSION": "off",
        "MIN_SCORE": "0",
        "KB_APPROVAL": "off",
        "KB_WATCH_SECONDS": "0",
        "API_KEYS": f"web:{RW_KEY},mcp:{RO_KEY}:ro,adm:{ADMIN_KEY}:admin",
    }
    old = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY"):
        os.environ.pop(key, None)

    from src.server import create_server

    httpd, _pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def call(method: str, path: str, key: str | None, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            return exc.code, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)

    print("只读 Key：能读")
    status, _ = call("GET", "/api/knowledge", RO_KEY)
    check("GET 知识库 200", status == 200, str(status))
    status, body = call("POST", "/api/ask", RO_KEY, {"query": "稳盈系列产品的起购金额是多少"})
    check("POST 提问 200（读语义 POST 不该被挡）", status == 200, str(status))
    check("问答真的答出来了", "1 元" in (body.get("answer") or ""),
          (body.get("answer") or "")[:60])
    status, _ = call("POST", "/api/search/debug", RO_KEY, {"query": "稳盈"})
    check("POST 检索调试 200", status == 200, str(status))

    print("只读 Key：不能写")
    payload = {"name": "新文档.md", "content": "# 新文档\n\n内容"}
    status, body = call("POST", "/api/knowledge/upload", RO_KEY, payload)
    check("上传被拒 403", status == 403, f"{status} {body}")
    check("错误码是 read_only_key（不是 unauthorized）",
          (body or {}).get("error") == "read_only_key", str(body))
    check("提示里说清了怎么改", "只读" in str((body or {}).get("message")),
          str((body or {}).get("message")))

    status, body = call("POST", "/api/knowledge/upload_file", RO_KEY,
                        {"name": "x.pptx", "data_b64": base64.b64encode(b"PK").decode()})
    check("上传文件被拒 403", status == 403, f"{status} {body}")

    status, body = call("POST", "/api/kb/approve", RO_KEY, {"change_id": "x"})
    check("审批被拒（只读也够不到管理员动作）", status in (403,), f"{status} {body}")

    status, body = call("POST", "/api/reload", RO_KEY, {})
    check("重建索引被拒 403", status == 403, f"{status} {body}")

    print("读写 Key 不受影响")
    status, _ = call("GET", "/api/knowledge", RW_KEY)
    check("读写 Key 读 200", status == 200, str(status))
    status, body = call("POST", "/api/knowledge/upload", RW_KEY, payload)
    check("读写 Key 能上传", status == 200, f"{status} {str(body)[:120]}")

    print("管理员作用域")
    status, body = call("POST", "/api/reload", ADMIN_KEY, {})
    check("admin 作用域的 Key 能调运维接口",
          status == 200, f"{status} {str(body)[:120]}")

    httpd.shutdown()
    httpd.server_close()
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    if FAILED:
        print(f"\nKEY SCOPE: {FAILED} FAILED")
        raise SystemExit(1)
    print("\nKEY SCOPE OK")


if __name__ == "__main__":
    main()
