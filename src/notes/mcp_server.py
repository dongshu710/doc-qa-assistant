"""MCP 服务端（stdio）：把笔记能力直接交给支持 MCP 的客户端。

为什么先做 stdio：跨客户端最稳，不需要端口、证书、跨域，进程由客户端拉起。
stdout 是协议通道，任何调试输出必须走 stderr——否则客户端会因为「多了一行日志」解析失败。
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any

from . import export as export_mod
from .model import NoteError
from .service import NoteConflict, NoteService
from .store import NoteNotFound, StoreBusy
from .tools import TOOLS

try:  # 单独把 notes 包拷走使用时也应当能跑
    from ..version import __version__
except ImportError:  # pragma: no cover
    __version__ = "0.0.0"

SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "agent-notes"


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def log(message: str) -> None:
    """诊断信息只写 stderr：stdout 被 JSON-RPC 独占。"""
    sys.stderr.write(f"[agent-notes] {message}\n")
    sys.stderr.flush()


def tools() -> list[dict]:
    return [{"name": item["function"]["name"],
             "description": item["function"]["description"],
             "inputSchema": item["function"]["parameters"]} for item in TOOLS]


def resources() -> list[dict]:
    return [
        {"uri": "notes://schema",
         "name": "笔记格式契约",
         "description": "Note v1 的字段、小节与容错规则；想直接改文件前先读这个。",
         "mimeType": "text/markdown"},
        {"uri": "notes://index",
         "name": "笔记索引",
         "description": "全部笔记的 id / 标题 / 标签 / 时间，最多 200 条。",
         "mimeType": "application/json"},
    ]


def read_resource(service: NoteService, uri: str) -> dict:
    if uri == "notes://schema":
        from .schema_doc import SCHEMA_DOC
        return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": SCHEMA_DOC}]}
    if uri == "notes://index":
        rows = service.list(limit=200)
        return {"contents": [{"uri": uri, "mimeType": "application/json",
                              "text": json.dumps({"count": len(rows), "items": rows},
                                                 ensure_ascii=False, indent=2)}]}
    if uri.startswith("notes://note/"):
        note_id = uri[len("notes://note/"):]
        data = service.get(note_id)
        return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": data["markdown"]}]}
    raise RpcError(-32602, f"未知资源：{uri}")


def call_tool(service: NoteService, name: str, args: dict) -> str:
    """执行一个工具，返回给模型看的文本（JSON 串）。异常在这里收敛成可读错误。"""
    if not isinstance(args, dict):
        raise RpcError(-32602, "arguments 必须是对象")
    try:
        if name == "save_conversation":
            payload = {key: args[key] for key in ("messages", "select", "hint", "source") if key in args}
            payload["keep_raw"] = bool(args.get("keep_raw", False))
            result = service.save(payload, commit=bool(args.get("commit", True)))
            return _brief({k: result[k] for k in ("id", "title", "kind", "tags", "digest",
                                                  "committed", "duplicate_of", "path",
                                                  "messages", "truncated")}
                          | {"markdown": result["markdown"][:4000]})
        if name == "search_notes":
            rows = service.list(tags=args.get("tag") or None, kind=args.get("kind"),
                                status=args.get("status"), since=args.get("since"),
                                limit=int(args.get("limit") or 10))
            return _brief({"count": len(rows), "items": rows})
        if name == "get_note":
            data = service.get(str(args.get("id") or ""))
            section = str(args.get("section") or "").strip()
            if section:
                hit = next((item for item in data["sections"] if item["title"] == section), None)
                if hit is None:
                    raise NoteError(f"这篇笔记没有「{section}」这一节；可选："
                                    + " / ".join(item["title"] for item in data["sections"]))
                return _brief({"id": data["id"], "title": data["title"], "section": section,
                               "body": hit["body"], "rev": data["rev"]})
            return _brief(data)
        if name == "update_note":
            changes = {key: args[key] for key in ("title", "tags", "kind", "status", "sections")
                       if key in args}
            data = service.patch(str(args.get("id") or ""), changes,
                                 base_rev=args.get("base_rev"), force=bool(args.get("force", False)))
            return _brief({"id": data["id"], "title": data["title"], "status": data["status"],
                           "tags": data["tags"], "rev": data["rev"]})
        if name == "delete_note":
            note_id = str(args.get("id") or "")
            if args.get("confirm") is not True:
                raise NoteError("删除需要用户确认：把 confirm 设为 true 再调用")
            return _brief({"ok": True, **service.delete(note_id)})
        if name == "note_stats":
            return _brief(service.stats())
        if name == "export_notes":
            out = str(args.get("out") or "").strip()
            if not out:
                raise NoteError("需要 out（导出文件路径）")
            result = export_mod.export(service, out, note_ids=args.get("ids") or None,
                                       fmt=str(args.get("format") or "html"),
                                       filters={"tags": args.get("tag") or None,
                                                "since": args.get("since")},
                                       title=str(args.get("title") or "我的笔记"))
            return _brief(result)
    except NoteNotFound as exc:
        raise NoteError(f"笔记不存在：{exc.note_id}") from exc
    except NoteConflict as exc:
        raise NoteError(f"这篇笔记已被改动（当前 rev={exc.rev}），请重新 get_note 后再改") from exc
    except StoreBusy as exc:
        raise NoteError(f"存储忙，请稍后重试：{exc}") from exc
    raise RpcError(-32601, f"未知工具：{name}")


def _brief(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


def handle(service: NoteService, request: dict) -> dict | None:
    """处理一条 JSON-RPC 消息；返回 None 表示这是通知，不该有响应。"""
    if not isinstance(request, dict):
        raise RpcError(-32600, "请求必须是 JSON 对象")
    method = request.get("method")
    is_notification = "id" not in request
    if not isinstance(method, str):
        raise RpcError(-32600, "缺少 method")

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "initialize":
        params = request.get("params") or {}
        wanted = str(params.get("protocolVersion") or "")
        version = wanted if wanted in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        return {"protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}, "resources": {"subscribe": False}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__,
                               "title": "个人笔记（对话整理与存储）"},
                "instructions": ("先 search_notes 看有没有存过的内容，再决定是否 save_conversation；"
                                 "save 前如果用户还在犹豫，用 commit=false 预览。"
                                 "内容以文件为真相，用户可能手工改过，改之前先 get_note 拿 rev。")}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tools()}
    if method == "tools/call":
        params = request.get("params") or {}
        name = str(params.get("name") or "")
        try:
            text = call_tool(service, name, params.get("arguments") or {})
        except (NoteError, ValueError) as exc:
            # 工具级失败照 MCP 约定返回 isError，而不是 JSON-RPC 错误：模型能看到原因并自行纠正
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        return {"content": [{"type": "text", "text": text}], "isError": False}
    if method == "resources/list":
        return {"resources": resources()}
    if method == "resources/read":
        params = request.get("params") or {}
        return read_resource(service, str(params.get("uri") or ""))
    if method == "prompts/list":
        return {"prompts": []}
    if is_notification:
        return None
    raise RpcError(-32601, f"不支持的方法：{method}")


def serve(service: NoteService, stdin=None, stdout=None) -> int:
    """逐行读 JSON-RPC：stdio 传输用换行分隔，一条消息一行。"""
    inp = stdin or sys.stdin
    out = stdout or sys.stdout
    for line in inp:
        text = line.strip()
        if not text:
            continue
        try:
            request = json.loads(text)
        except json.JSONDecodeError as exc:
            _write(out, {"jsonrpc": "2.0", "id": None,
                         "error": {"code": -32700, "message": f"JSON 解析失败：{exc.msg}"}})
            continue
        try:
            result = handle(service, request)
        except RpcError as exc:
            error = {"code": exc.code, "message": exc.message}
            if exc.data is not None:
                error["data"] = exc.data
            if isinstance(request, dict) and "id" in request:
                _write(out, {"jsonrpc": "2.0", "id": request.get("id"), "error": error})
            continue
        except Exception as exc:  # noqa: BLE001 —— 一条坏消息不能拖垮整个会话
            log(f"handler crashed: {type(exc).__name__}: {exc}")
            traceback.print_exc(file=sys.stderr)
            if isinstance(request, dict) and "id" in request:
                _write(out, {"jsonrpc": "2.0", "id": request.get("id"),
                             "error": {"code": -32603, "message": f"服务端异常：{type(exc).__name__}"}})
            continue
        if result is None or not isinstance(request, dict) or "id" not in request:
            continue
        _write(out, {"jsonrpc": "2.0", "id": request.get("id"), "result": result})
    return 0


def _write(out, payload: dict) -> None:
    out.write(json.dumps(payload, ensure_ascii=False) + "\n")
    out.flush()


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="notes-mcp", description="个人笔记 MCP 服务（stdio）")
    parser.add_argument("--home", help="笔记根目录，默认 NOTE_HOME 或 ~/agent-notes")
    args = parser.parse_args(argv)
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        service = NoteService(args.home)
    except OSError as exc:
        log(f"存储初始化失败：{type(exc).__name__}: {exc}")
        return 3
    log(f"ready home={service.store.home} version={__version__}")
    return serve(service)


if __name__ == "__main__":
    raise SystemExit(main())
