"""笔记 HTTP 接口的端到端测试：CRUD、乐观锁、删除确认、鉴权、契约。

不起外部进程，直接在进程内起服务；不联网、不依赖 pytest。
"""

from __future__ import annotations

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

PAYLOAD = {
    "messages": [
        {"role": "user", "text": "出口退税的退税率按什么标准执行？"},
        {"role": "assistant", "text": "根据办法第十二条，退税率按出口货物适用税率执行，2026-11-01 起统一按 13% 执行。决定由财务部在每月 5 日前复核申报表。"},
        {"role": "user", "text": "还有别的注意事项吗？"},
        {"role": "assistant", "text": "待办：财务部复核申报表；下一步将口径同步给报关行。"},
    ],
    "hint": {"title": "出口退税申报口径确认", "kind": "decision", "tags": ["税务", "出口退税"]},
    "source": {"agent": "test-suite", "session": "sess_api"},
}


def call(port: int, method: str, path: str, body: dict | None = None,
         headers: dict | None = None, raw: bytes | None = None):
    data = raw if raw is not None else (json.dumps(body, ensure_ascii=False).encode("utf-8")
                                       if body is not None else None)
    base = {"Content-Type": "application/json"} if data is not None else {}
    request = urllib.request.Request(f"http://{HOST}:{port}{path}", data=data,
                                     headers={**base, **(headers or {})}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            text = resp.read().decode("utf-8")
            return resp.status, dict(resp.headers), (json.loads(text) if text else None)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8")
        return exc.code, dict(exc.headers), (json.loads(text) if text else None)


def start_server(home: Path, extra_env: dict | None = None):
    tmp = home.parent
    seed = tmp / "seed"
    if not seed.exists():
        seed.mkdir(parents=True)
        (seed / "a.md").write_text("# 甲\n\n## 要素\n\n起购金额 1000 元。\n", encoding="utf-8")
    env = {
        "NOTE_HOME": str(home),
        "KB_DIR": str(tmp / "kb"), "KB_SEED_DIR": str(seed),
        "KEYWORD_INDEX": str(tmp / "keywords.json"),
        "RETRIEVAL": "bm25", "QUERY_EXPANSION": "off", "KB_APPROVAL": "off",
        "RATE_LIMIT_BURST": "50",
    }
    env.update(extra_env or {})
    for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY"):
        os.environ.pop(key, None)
    os.environ.update(env)
    from src.server import create_server
    httpd, _pipe = create_server(HOST, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="notes-api-"))
    httpd, port = start_server(tmp / "store")
    try:
        # 1. 保存 → 201 + 文件落盘
        status, _, body = call(port, "POST", "/api/notes", PAYLOAD)
        assert status == 201 and body["ok"] and body["committed"], (status, body)
        note_id = body["id"]
        path = Path(body["path"])
        assert path.exists(), path
        print("POST /api/notes → 201 OK:", note_id)

        # 2. 内容重复 → 200 + duplicate_of，不产生新文件
        files_before = len(list((tmp / "store").rglob("*.md")))
        status, _, dup = call(port, "POST", "/api/notes", PAYLOAD)
        assert status == 200 and dup["duplicate_of"] == note_id and not dup["committed"], dup
        assert len(list((tmp / "store").rglob("*.md"))) == files_before
        print("重复保存 → duplicate_of OK")

        # 3. commit=false 只预览
        status, _, draft = call(port, "POST", "/api/notes", {**PAYLOAD, "commit": False})
        assert status == 200 and draft["committed"] is False and draft["path"] is None, draft
        assert "## 摘要" in draft["markdown"]
        assert len(list((tmp / "store").rglob("*.md"))) == files_before
        print("commit=false 预览 OK")

        # 3.5 创建时的枚举校验：PATCH 拦得住的值，POST 也不能放进来
        status, _, bad_status = call(port, "POST", "/api/notes", {
            "messages": [{"role": "user", "content": "状态校验"}],
            "hint": {"status": "bogus"},
        })
        assert status == 400 and "status" in bad_status["message"], (status, bad_status)
        print("创建时状态枚举校验 OK")

        # 4. 列表与筛选
        status, _, listing = call(port, "GET", "/api/notes")
        assert status == 200 and listing["count"] == 1, listing
        status, _, by_tag = call(port, "GET", "/api/notes?tag=%E7%A8%8E%E5%8A%A1")
        assert by_tag["count"] == 1, by_tag
        status, _, empty = call(port, "GET", "/api/notes?tag=nope")
        assert empty["count"] == 0, empty
        status, _, bad = call(port, "GET", "/api/notes?limit=abc")
        assert status == 400 and bad["error"] == "invalid_argument", (status, bad)
        print("列表与筛选 OK")

        # 5. 单篇读取 + 指定小节
        status, _, note = call(port, "GET", f"/api/notes/{note_id}")
        assert status == 200 and note["rev"] and note["title"] == "出口退税申报口径确认", note
        rev = note["rev"]
        status, _, section = call(port, "GET", f"/api/notes/{note_id}?section=%E6%91%98%E8%A6%81")
        assert status == 200 and section["body"].strip(), section
        status, _, missing = call(port, "GET", f"/api/notes/{note_id}?section=nope")
        assert missing["body"] == ""
        print("单篇读取 OK:", rev)

        # 6. PATCH：缺 rev → 400；rev 错 → 409；rev 对 → 200
        status, _, err = call(port, "PATCH", f"/api/notes/{note_id}", {"changes": {"title": "新标题"}})
        assert status == 400 and "base_rev" in err["message"], (status, err)
        status, _, conflict = call(port, "PATCH", f"/api/notes/{note_id}",
                                   {"base_rev": "deadbeef", "changes": {"title": "新标题"}})
        assert status == 409 and conflict["rev"] == rev, (status, conflict)
        status, _, updated = call(port, "PATCH", f"/api/notes/{note_id}",
                                  {"base_rev": rev, "changes": {"title": "新标题", "tags": ["税务"]}})
        assert status == 200 and updated["title"] == "新标题" and updated["tags"] == ["税务"], updated
        assert updated["rev"] != rev
        print("PATCH 乐观锁 OK")

        # 7. PATCH 小节：改一条、删一条
        status, _, edited = call(port, "PATCH", f"/api/notes/{note_id}", {
            "base_rev": updated["rev"],
            "changes": {"sections": {"待办": "- [ ] 报关行确认口径", "引用": ""}},
        })
        assert status == 200, edited
        titles = [item["title"] for item in edited["sections"]]
        assert "待办" in titles and "引用" not in titles, titles
        status, _, finalized = call(port, "PATCH", f"/api/notes/{note_id}", {
            "base_rev": edited["rev"], "changes": {"status": "final"}})
        assert status == 200 and finalized["status"] == "final", finalized
        status, _, bad_status = call(port, "PATCH", f"/api/notes/{note_id}", {
            "base_rev": finalized["rev"], "changes": {"status": "nope"}})
        assert status == 400 and "status" in bad_status["message"], bad_status
        status, _, bad_field = call(port, "PATCH", f"/api/notes/{note_id}", {
            "base_rev": finalized["rev"], "changes": {"nope": 1}})
        assert status == 400 and "不支持" in bad_field["message"], bad_field
        print("PATCH 小节 OK")

        # 8. 非法请求体
        status, _, bad_json = call(port, "POST", "/api/notes", raw=b"{not json")
        assert status == 400 and "JSON" in bad_json["message"], bad_json
        status, _, empty = call(port, "POST", "/api/notes", {})
        assert status == 400 and empty["error"] == "invalid_argument", empty
        status, _, bad_id = call(port, "GET", "/api/notes/bad%20id")
        assert status == 400, (status, bad_id)
        print("非法输入 OK")

        # 9. DELETE：缺确认 → 400；带确认 → 200 且进回收站
        status, _, need = call(port, "DELETE", f"/api/notes/{note_id}")
        assert status == 400 and need["error"] == "confirm_required", (status, need)
        assert path.exists(), "未确认时不该动文件"
        status, _, deleted = call(port, "DELETE", f"/api/notes/{note_id}?confirm=1")
        assert status == 200 and Path(deleted["trashed"]).exists(), deleted
        assert not path.exists()
        status, _, gone = call(port, "GET", f"/api/notes/{note_id}")
        assert status == 404 and gone["error"] == "not_found", (status, gone)
        status, _, listing = call(port, "GET", "/api/notes")
        assert listing["count"] == 0, listing
        print("DELETE 确认与软删除 OK")

        # 10. 统计、CORS 预检、工具声明、契约
        status, _, stats = call(port, "GET", "/api/notes/stats")
        assert status == 200 and stats["notes"] == 0, stats
        status, headers, _ = call(port, "OPTIONS", "/api/notes")
        assert status == 204 and "GET" in (headers.get("Allow") or ""), (status, headers)
        status, _, tools = call(port, "GET", "/tools.json")
        names = [item["function"]["name"] for item in tools["tools"]]
        assert status == 200 and len(names) == 7 and "export_notes" in names, names
        status, _, spec = call(port, "GET", "/openapi.json")
        assert "/api/notes" in spec["paths"] and "/api/notes/{id}" in spec["paths"], spec["paths"].keys()
        assert any(tag["name"] == "笔记" for tag in spec["tags"])
        print("统计 / 预检 / 工具声明 / OpenAPI OK")
    finally:
        httpd.shutdown()

    # 11. 鉴权：配了 API_KEYS 就必须带 Key
    tmp2 = Path(tempfile.mkdtemp(prefix="notes-api-auth-"))
    httpd2, port2 = start_server(tmp2 / "store", {"API_KEYS": "web:sk_notes_123456"})
    try:
        status, headers, denied = call(port2, "POST", "/api/notes", PAYLOAD)
        assert status == 401 and denied["error"] == "unauthorized", (status, denied)
        assert "bearer" in (headers.get("WWW-Authenticate") or "").lower(), headers
        status, _, created = call(port2, "POST", "/api/notes", PAYLOAD,
                                  {"Authorization": "Bearer sk_notes_123456"})
        assert status == 201, (status, created)
        status, _, listing = call(port2, "GET", "/api/notes",
                                  headers={"X-API-Key": "sk_notes_123456"})
        assert status == 200 and listing["count"] == 1, listing
        print("鉴权 OK：无 Key 401 / Bearer 201 / X-API-Key 200")
    finally:
        httpd2.shutdown()

    print("\nNOTES API OK")


if __name__ == "__main__":
    main()
