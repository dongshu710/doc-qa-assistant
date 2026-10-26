"""MCP stdio 协议测试：不依赖任何第三方 MCP SDK，纯 JSON-RPC 往返。

覆盖的是「客户端真会做的事」：握手、列工具、调工具、读资源、坏消息不崩。
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("NOTE_HOME", tempfile.mkdtemp(prefix="mcp-notes-"))

# 直接 `python tests/x.py` 跑时，sys.path[0] 是 tests/，仓库根不在里面。
# CI 里没有 PYTHONPATH，缺这段就是 ModuleNotFoundError: No module named 'src'。
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.notes import mcp_server as mcp  # noqa: E402
from src.notes.service import NoteService  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))


def run(service: NoteService, *messages: dict) -> list[dict]:
    """一次喂多条消息，返回所有响应（通知不产生响应）。"""
    stdin = io.StringIO("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in messages))
    stdout = io.StringIO()
    mcp.serve(service, stdin=stdin, stdout=stdout)
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


def call(service: NoteService, rid: int, name: str, args: dict) -> dict:
    reply = run(service, {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                          "params": {"name": name, "arguments": args}})[0]
    return reply["result"]


def main() -> int:
    home = tempfile.mkdtemp(prefix="mcp-home-")
    service = NoteService(home)

    # 1) 握手：客户端报的版本受支持就照抄，否则回落到自己支持的
    hello = run(service, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                     "clientInfo": {"name": "test", "version": "1"}}})
    init = hello[0]["result"]
    check("握手返回同一协议版本", init["protocolVersion"] == "2025-03-26", init["protocolVersion"])
    check("声明 tools 与 resources 能力",
          "tools" in init["capabilities"] and "resources" in init["capabilities"])
    check("serverInfo 带名字与版本", init["serverInfo"]["name"] == "agent-notes"
          and bool(init["serverInfo"]["version"]))

    odd = run(service, {"jsonrpc": "2.0", "id": 2, "method": "initialize",
                        "params": {"protocolVersion": "1999-01-01"}})
    check("未知协议版本回落到受支持版本",
          odd[0]["result"]["protocolVersion"] in mcp.SUPPORTED_PROTOCOLS,
          odd[0]["result"]["protocolVersion"])

    # 2) 通知不产生响应
    silent = run(service, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    check("initialized 通知不返回内容", silent == [], str(silent))

    # 3) 工具清单与 JSON Schema
    listed = run(service, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})[0]["result"]["tools"]
    names = [item["name"] for item in listed]
    check("工具数量为 7", len(listed) == 7, str(names))
    check("工具名齐全", set(names) == {"save_conversation", "search_notes", "get_note",
                                       "update_note", "delete_note", "note_stats",
                                       "export_notes"}, str(names))
    save_schema = next(item for item in listed if item["name"] == "save_conversation")["inputSchema"]
    check("save_conversation 有 inputSchema 且必填 messages",
          save_schema["type"] == "object" and save_schema["required"] == ["messages"])

    # 4) 保存 → 读 → 搜 → 统计
    payload = {
        "messages": [
            {"role": "user", "text": "出口退税的退税率按什么标准执行？"},
            {"role": "assistant", "text": "按 13% 执行。决定由财务部每月 5 日前复核申报表。"},
        ],
        "hint": {"title": "退税率口径", "kind": "decision", "tags": ["税务", "出口退税"]},
        "source": {"agent": "test-agent"},
    }
    saved = call(service, 10, "save_conversation", payload)
    check("保存成功且未标错", saved["isError"] is False, saved["content"][0]["text"][:80])
    brief = json.loads(saved["content"][0]["text"])
    note_id = brief["id"]
    check("返回 id 与标题", bool(note_id) and brief["title"] == "退税率口径", str(brief)[:120])
    check("返回 markdown 供模型确认", "## 摘要" in brief["markdown"])

    got = json.loads(call(service, 11, "get_note", {"id": note_id})["content"][0]["text"])
    check("按 id 读回同一篇", got["id"] == note_id and got["rev"], got.get("rev", ""))
    section = json.loads(call(service, 12, "get_note",
                              {"id": note_id, "section": "决策"})["content"][0]["text"])
    check("只取一节时返回该节正文", section["section"] == "决策" and "复核" in section["body"],
          str(section)[:120])

    found = json.loads(call(service, 13, "search_notes", {"tag": ["税务"]})["content"][0]["text"])
    check("按标签搜到 1 篇", found["count"] == 1, str(found)[:120])
    miss = json.loads(call(service, 14, "search_notes", {"tag": ["不存在"]})["content"][0]["text"])
    check("搜不到时返回空列表而不是报错", miss["count"] == 0)

    stats = json.loads(call(service, 15, "note_stats", {})["content"][0]["text"])
    check("统计与磁盘一致", stats["notes"] == 1, str(stats)[:120])

    # 5) 修改：带 rev 成功，旧 rev 被拒
    updated = call(service, 16, "update_note",
                   {"id": note_id, "base_rev": got["rev"], "status": "final"})
    check("带正确 rev 可改状态", json.loads(updated["content"][0]["text"])["status"] == "final")
    stale = call(service, 17, "update_note",
                 {"id": note_id, "base_rev": got["rev"], "title": "旧 rev 覆盖"})
    check("旧 rev 被拒并提示重新读取",
          stale["isError"] is True and "rev" in stale["content"][0]["text"],
          stale["content"][0]["text"][:80])

    # 6) 导出：文件真的写出来了，且不含外链资源
    out = os.path.join(home, "exports", "all.html")
    exported = json.loads(call(service, 18, "export_notes", {"out": out})["content"][0]["text"])
    html = open(out, encoding="utf-8").read()
    check("导出 html 落盘且计数正确", exported["count"] == 1 and os.path.exists(out))
    check("导出文件自包含（无外部 css/js/字体）",
          "<link" not in html and "src=\"http" not in html and "@import" not in html)

    # 7) 删除需要确认
    refused = call(service, 19, "delete_note", {"id": note_id})
    check("未确认时拒绝删除", refused["isError"] is True and "确认" in refused["content"][0]["text"])
    check("拒绝后文件仍在", os.path.exists(got["markdown"]) is False and service.get(note_id)["id"] == note_id)
    removed = call(service, 20, "delete_note", {"id": note_id, "confirm": True})
    check("确认后移入回收站", json.loads(removed["content"][0]["text"])["trashed"].endswith(".md"))

    # 8) 资源
    res = run(service, {"jsonrpc": "2.0", "id": 30, "method": "resources/list"})[0]["result"]["resources"]
    uris = [item["uri"] for item in res]
    check("资源列表含 schema 与 index", "notes://schema" in uris and "notes://index" in uris, str(uris))
    schema_text = run(service, {"jsonrpc": "2.0", "id": 31, "method": "resources/read",
                                "params": {"uri": "notes://schema"}})[0]["result"]["contents"][0]["text"]
    check("schema 资源描述 front matter 与容错",
          "front matter" in schema_text and "note/v1" in schema_text)

    # 9) 协议级错误
    unknown = run(service, {"jsonrpc": "2.0", "id": 40, "method": "no/such/method"})[0]
    check("未知方法返回 -32601", unknown["error"]["code"] == -32601, str(unknown)[:120])
    bad_tool = run(service, {"jsonrpc": "2.0", "id": 41, "method": "tools/call",
                             "params": {"name": "no_such_tool", "arguments": {}}})[0]
    check("未知工具按协议返 -32601，不假装执行成功",
          bad_tool["error"]["code"] == -32601, str(bad_tool)[:120])

    broken = io.StringIO("{不是 JSON}\n")
    out = io.StringIO()
    mcp.serve(service, stdin=broken, stdout=out)
    parse_error = json.loads(out.getvalue().splitlines()[0])
    check("坏 JSON 返回 -32700 且会话继续", parse_error["error"]["code"] == -32700)

    blank = io.StringIO("\n\n")
    out = io.StringIO()
    mcp.serve(service, stdin=blank, stdout=out)
    check("空行被忽略", out.getvalue() == "")

    # 10) 笔记目录自带 AGENTS.md，换智能体也能看懂
    guide = os.path.join(home, "AGENTS.md")
    check("笔记根目录自动生成 AGENTS.md", os.path.exists(guide))
    if os.path.exists(guide):
        text = open(guide, encoding="utf-8").read()
        open(guide, "w", encoding="utf-8").write(text + "\n用户自己的备注\n")
        NoteService(home)
        check("用户改过的 AGENTS.md 不被覆盖",
              "用户自己的备注" in open(guide, encoding="utf-8").read())

    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
        return 1
    print("MCP OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
