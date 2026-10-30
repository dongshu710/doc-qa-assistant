"""笔记的 HTTP 契约层：只做协议转换，业务全部落在 NoteService。

放这里而不是塞进 server.py 的原因：后面还要接 MCP，两套协议必须共用同一份
参数语义与错误码，否则一个客户端能存、另一个存不进去，问题极难定位。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import quote, unquote

from . import assets as assets_mod, export as export_mod
from .model import NoteError
from .service import NoteConflict, NoteService
from .store import NoteNotFound, StoreBusy

ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]{0,80}$")


class ApiError(Exception):
    def __init__(self, status: int, error: str, message: str,
                 headers: dict | None = None, **extra):
        super().__init__(message)
        self.status = status
        self.payload = {"ok": False, "error": error, "message": message, **extra}
        self.headers = headers or {}


def dispatch(service: NoteService | None, method: str, path: str,
             query: dict, body: dict | None) -> tuple[int, dict, dict]:
    """返回 (状态码, 响应体, 额外响应头)。所有异常在这里收敛成结构化错误。"""
    if service is None:
        raise ApiError(503, "notes_unavailable", "笔记存储未初始化，请检查 NOTE_HOME 是否可写")

    rest = path[len("/api/notes"):].strip("/")
    try:
        if rest == "":
            if method == "GET":
                return 200, _list(service, query), {}
            if method == "POST":
                return _create(service, body)
            raise ApiError(405, "method_not_allowed", "该地址只支持 GET / POST",
                           headers={"Allow": "GET, POST, OPTIONS"})
        if rest == "export":
            if method != "GET":
                raise ApiError(405, "method_not_allowed", "export 只支持 GET",
                               headers={"Allow": "GET, OPTIONS"})
            return 200, _export(service, query), {}
        if rest == "stats":
            if method != "GET":
                raise ApiError(405, "method_not_allowed", "stats 只支持 GET",
                               headers={"Allow": "GET, OPTIONS"})
            return 200, {"ok": True, **service.stats()}, {}
        if rest == "rebuild":
            # 检索索引是派生的，删了能重建；重建是显式动作，不受「查询时懒补」的额度限制
            if method != "POST":
                raise ApiError(405, "method_not_allowed", "rebuild 只支持 POST",
                               headers={"Allow": "POST, OPTIONS"})
            semantic = "auto"
            if isinstance(body, dict) and body.get("semantic") is not None:
                semantic = str(body["semantic"]).lower()
            return 200, {"ok": True, **service.rebuild_search(semantic)}, {}
        parts = [item for item in rest.split("/") if item]
        if len(parts) >= 2 and parts[1] == "assets":
            return _assets(service, parts, method, query, body)
        if not ITEM_ID.match(rest):
            raise ApiError(400, "invalid_argument", f"笔记 id 不合法：{rest}")
        note_id = rest
        if method == "GET":
            note = service.get(note_id)
            section = _one(query, "section")
            if section:
                hit = next((item for item in note["sections"] if item["title"] == section), None)
                return 200, {"ok": True, "id": note_id, "section": section,
                             "body": hit["body"] if hit else "", "rev": note["rev"]}, {}
            # 页面要拿它调 /api/files/raw 直接改原文；导出走 service.get，不带这个字段
            note["path"] = service.rel_path(note_id)
            return 200, {"ok": True, **note}, {}
        if method == "PATCH":
            return 200, _patch(service, note_id, body, query), {}
        if method == "DELETE":
            return 200, _delete(service, note_id, body, query), {}
        raise ApiError(405, "method_not_allowed", "该地址支持 GET / PATCH / DELETE",
                       headers={"Allow": "GET, PATCH, DELETE, OPTIONS"})
    except NoteNotFound as exc:
        raise ApiError(404, "not_found", str(exc), id=exc.note_id) from exc
    except NoteConflict as exc:
        raise ApiError(409, "conflict",
                       "笔记已被修改，请重新 GET 拿到新的 rev 后再改",
                       rev=exc.rev) from exc
    except StoreBusy as exc:
        raise ApiError(503, "busy", str(exc), headers={"Retry-After": "1"}) from exc
    except assets_mod.AssetError as exc:
        # 错误码沿用笔记接口已有的词汇，不为附件另立一套：
        # 客户端按 error 分支，多一个同义码只是多一处漏判
        code = {404: "not_found", 413: "payload_too_large"}.get(exc.status, "invalid_argument")
        raise ApiError(exc.status, code, str(exc)) from exc
    except NoteError as exc:
        raise ApiError(400, "invalid_argument", str(exc)) from exc


def _assets(service: NoteService, parts: list[str], method: str,
            query: dict, body: dict | None) -> tuple[int, dict, dict]:
    """附件：`/api/notes/{id}/assets[/{name}]`。

    单个文件的 GET 返回 `__binary__` 标记，由 handler 层换成原始字节写出。
    为什么不在这一层直接写 HTTP：dispatch 是协议无关的（MCP 也复用它的语义），
    一旦这里开始碰 `wfile`，以后想给 MCP 加附件就得再写一份。
    """
    note_id = parts[0]
    if not ITEM_ID.match(note_id):
        raise ApiError(400, "invalid_argument", f"笔记 id 不合法：{note_id}")
    if len(parts) == 2:
        if method == "GET":
            rows = service.list_assets(note_id)
            total = sum(int(row.get("size") or 0) for row in rows)
            return 200, {"ok": True, "count": len(rows), "bytes": total, "items": rows}, {}
        if method == "POST":
            return _upload_asset(service, note_id, body)
        raise ApiError(405, "method_not_allowed", "附件集合支持 GET / POST",
                       headers={"Allow": "GET, POST, OPTIONS"})
    if len(parts) == 3:
        # 必须先解码：URL 里的中文文件名是百分号编码的（`架构图.png` → `%E6%9E%B6...`），
        # 不解码就永远 404，而中文文件名在这里是常态不是边缘情况。
        # 先解码再交给 resolve 校验——顺序反了会把 `%2F` 当成普通字符放过穿越。
        name = unquote(parts[2])
        if method == "GET":
            data, mime = service.read_asset(note_id, name)
            return 200, {"__binary__": True, "content": data, "mime": mime}, {
                "Content-Disposition": _disposition(name, mime)}
        if method == "DELETE":
            confirm = (_one(query, "confirm") or "").lower() in ("1", "true", "yes")
            if isinstance(body, dict) and body.get("confirm") is True:
                confirm = True
            if not confirm:
                raise ApiError(400, "confirm_required",
                               "删除附件需要确认：加 ?confirm=1 或请求体 {\"confirm\": true}；"
                               "这个删除不进回收站")
            return 200, {"ok": True, **service.delete_asset(note_id, name)}, {}
        raise ApiError(405, "method_not_allowed", "单个附件支持 GET / DELETE",
                       headers={"Allow": "GET, DELETE, OPTIONS"})
    raise ApiError(404, "not_found", "接口不存在")


def _upload_asset(service: NoteService, note_id: str, body: dict | None) -> tuple[int, dict, dict]:
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_argument", "请求体必须是 JSON 对象")
    name = str(body.get("name") or "").strip()
    if not name:
        raise ApiError(400, "invalid_argument", "需要 name（文件名，带扩展名，例如 架构图.png）")
    # 解码的容错口径统一放在 assets 里：HTTP 与 MCP 两条路共用一份，
    # 免得「前端给 data URL、后端只要裸 base64」这类差异各自长一套
    payload = assets_mod.decode_data(body.get("data"))
    # 返回的 markdown 片段可以直接粘进正文，省得调用方再拼一次路径
    return 201, {"ok": True, **service.save_asset(note_id, name, payload)}, {}


def _disposition(name: str, mime: str) -> str:
    """图片与 PDF 内联显示，其余当附件下载。

    HTML 不在允许上传的类型里，但即便如此也不给 `inline`——同源下的 HTML
    就是一个能调本服务接口的页面。
    """
    inline = mime.startswith("image/") or mime == "application/pdf"
    return f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(name)}"


def _create(service: NoteService, body: dict | None) -> tuple[int, dict, dict]:
    """新建笔记。`commit=false` 只渲染不落盘，用于「先给人看一眼再存」。"""
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_argument", "请求体必须是 JSON 对象")
    commit = body.get("commit", True)
    if not isinstance(commit, bool):
        raise ApiError(400, "invalid_argument", "commit 必须是布尔值（false = 只预览不落盘）")
    keep_raw = body.get("keep_raw")
    if keep_raw is not None and not isinstance(keep_raw, bool):
        raise ApiError(400, "invalid_argument", "keep_raw 必须是布尔值")
    result = service.save(body, commit=commit, keep_raw=keep_raw,
                          digest_mode=body.get("digest"))
    return (201 if result["committed"] else 200), result, {}


def _export(service: NoteService, query: dict) -> dict:
    """导出返回内容本身（而不是写服务器磁盘）：浏览器拿到就能下载，服务端不落文件。"""
    fmt = (_one(query, "format") or "html").lower()
    if fmt not in ("html", "json"):
        raise ApiError(400, "invalid_argument", "format 只能是 html 或 json")
    ids = [str(item) for item in (query.get("id") or []) if str(item).strip()]
    if ids:
        notes = [service.get(item) for item in ids]
    else:
        rows = service.list(tags=query.get("tag") or None, kind=_one(query, "kind"),
                            status=_one(query, "status"), since=_one(query, "since"),
                            limit=500)
        notes = [service.get(row["id"]) for row in rows]
    title = _one(query, "title") or "我的笔记"
    if fmt == "html":
        text = export_mod.render_html(notes, title=title, home=service.store.home)
        mime, ext = "text/html", "html"
    else:
        text = json.dumps(export_mod.bundle(notes), ensure_ascii=False, indent=2)
        mime, ext = "application/json", "json"
    return {"ok": True, "format": fmt, "count": len(notes), "mime": mime,
            "filename": f"notes-{datetime.now().strftime('%Y%m%d-%H%M')}.{ext}",
            "bytes": len(text.encode("utf-8")), "content": text}


def _list(service: NoteService, query: dict) -> dict:
    try:
        limit = int(_one(query, "limit") or 20)
    except ValueError:
        raise ApiError(400, "invalid_argument", "limit 必须是整数") from None
    if limit < 0:
        raise ApiError(400, "invalid_argument", "limit 不能为负，至少给 1（想取全部请用导出）")
    limit = min(limit, 200)
    # `q` 与 `query` 都收：前者给页面，后者更贴近「搜一下」的自然说法
    text = _one(query, "q") or _one(query, "query") or ""
    result = service.search(text, tags=query.get("tag") or None, kind=_one(query, "kind"),
                            status=_one(query, "status"), since=_one(query, "since"),
                            limit=limit, semantic=(_one(query, "semantic") or "auto").lower())
    rows = result["items"]
    return {"ok": True, "count": len(rows), "items": rows, "search": result["search"]}


def _patch(service: NoteService, note_id: str, body: dict | None, query: dict) -> dict:
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_argument", "请求体必须是 JSON 对象")
    changes = body.get("changes")
    if changes is None:
        changes = {key: body[key] for key in ("title", "tags", "status", "kind", "sections")
                   if key in body}
    base_rev = body.get("base_rev") or _one(query, "base_rev")
    force = body.get("force") is True or (_one(query, "force") or "").lower() in ("1", "true", "yes")
    return {"ok": True, **service.patch(note_id, changes, base_rev=base_rev, force=force)}


def _delete(service: NoteService, note_id: str, body: dict | None, query: dict) -> dict:
    confirm = (_one(query, "confirm") or "").lower() in ("1", "true", "yes")
    if isinstance(body, dict) and body.get("confirm") is True:
        confirm = True
    if not confirm:
        raise ApiError(400, "confirm_required",
                       "删除需要确认：加 ?confirm=1 或请求体 {\"confirm\": true}；删除只是移入 .trash，可找回")
    result = service.delete(note_id)
    return {"ok": True, **result,
            "restore_hint": "文件在 .trash 里，改名移回 notes/ 即可恢复"}


def _one(query: dict, key: str) -> str | None:
    values = query.get(key) if isinstance(query, dict) else None
    if not values:
        return None
    value = values[0] if isinstance(values, list) else values
    value = str(value).strip()
    return value or None
