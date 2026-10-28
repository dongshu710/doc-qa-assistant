"""资源接口：笔记 / 会话 / 文件 / 存储 / 设置。

为什么单独一层：这五组接口共用同一套存储区与鉴权，改动也常常一起发生。
"""
from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
import json
import os
import pathlib
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import (appconfig, backup, casegen, evaluator, fileops, ingest, jsonl, kbstore,
                routing, security, settings_ops, suggest)
from .. import update as update_mod
from ..auth import ApiKeyStore, safe_equal
from ..config import api_key, load_settings
from ..guards import Guards
from ..metrics import summarize
from ..metrics_exporter import Metrics
from ..notes.api import ApiError
from ..notes.api import dispatch as notes_dispatch
from ..notes.service import NoteService
from ..notes.tools import tools_payload as notes_tools_payload
from ..openapi import build_spec
from ..pipeline import RAGPipeline
from ..theme import FILES_PAGE
from ..threadstore import ThreadError, ThreadStore
from ..version import __version__
from ..web_pages import ASK_HTML, KB_HTML
from .common import (ALLOWED_EXT, DOC_B64_MAX_BYTES, DOC_MAX_BYTES, MAX_BODY_BYTES,
                     NOTES_MAX_BYTES, SSE_HEARTBEAT_S, SSE_MAX_SECONDS, UPLOAD_MAX_BYTES,
                     _knowledge_dir, _open_folder, _raw_dir, _read_jsonl,
                     _safe_doc_name, _safe_kb_name)


def make_resources(deps):
    # 原来这些名字是 create_server() 的闭包；拆开后由组合根显式传入。
    project_root = deps.project_root
    settings = deps.settings
    metrics = deps.metrics
    pipe = deps.pipe
    store = deps.store
    log_dir = deps.log_dir
    guards = deps.guards
    api_keys = deps.api_keys
    note_ref = deps.note_ref
    feedback_path = deps.feedback_path
    feedback_cases_path = deps.feedback_cases_path
    doc_cases_path = deps.doc_cases_path
    run_report_path = deps.run_report_path
    raw_dir = deps.raw_dir
    kb_dir = deps.kb_dir
    async_reload = deps.async_reload
    reload_kb = deps.reload_kb
    index_payload = deps.index_payload
    index_fields = deps.index_fields
    _reopen_notes = deps._reopen_notes
    _repo_url = deps._repo_url
    _downloads = deps._downloads
    _mcp_config = deps._mcp_config
    _probe_llm = deps._probe_llm
    _storage_report = deps._storage_report
    _clear_index = deps._clear_index
    _total_bytes = deps._total_bytes
    _settings_payload = deps._settings_payload
    _runtime_warnings = deps._runtime_warnings
    _setup_state = deps._setup_state
    _apply_setup = deps._apply_setup
    _claude_config_path = deps._claude_config_path
    _picker_command = deps._picker_command
    _pick_folder = deps._pick_folder
    _count_notes = deps._count_notes
    _copy_notes = deps._copy_notes

    class ResourcesRoutes:
        # HTTP/1.1 + 定长响应 = 连接可复用，省掉每请求一次 TCP 握手。
        # timeout 必须有：keep-alive 下空闲连接会占住线程，不能无限等。
        protocol_version = "HTTP/1.1"
        timeout = 20

        # 只压缩文本类；已经在压缩格式里的（图片）再压是负收益
        COMPRESSIBLE = frozenset({
            "text/html", "text/plain", "text/markdown", "text/css",
            "application/json", "application/javascript", "text/javascript",
            "image/svg+xml",
        })

        def _notes_guard(self) -> dict | None:
            """配了 API_KEYS 就必须带 Key：笔记是个人数据，不能只靠「本机」当保护。"""
            _key_name, err = self._api_auth()
            if not err:
                return None
            metrics.inc("rag_unauthorized_total")
            guards.audit.write("notes.unauthorized", client=self._client(),
                               path=self.path[:200], reason=err)
            return {"ok": False, "error": "unauthorized",
                    "message": "需要 API Key：Authorization: Bearer <key> 或 X-API-Key"}
        def _read_note_body(self) -> tuple[dict | None, str | None]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None, "Content-Length 不合法"
            if length <= 0:
                return {}, None
            if length > NOTES_MAX_BYTES:
                return None, f"请求体超过 {NOTES_MAX_BYTES} 字节"
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return None, "请求体不是合法 JSON"
            if not isinstance(data, dict):
                return None, "请求体必须是 JSON 对象"
            return data, None
        def _notes(self, method: str, path: str, query: dict, body: dict | None) -> None:
            cors = self._cors_headers()
            if method == "OPTIONS":
                self.send_response(204)
                for key, value in {**cors, "Allow": "GET, POST, PATCH, DELETE, OPTIONS"}.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            denied = self._notes_guard()
            if denied:
                self._json(denied, 401, {**cors, "WWW-Authenticate": 'Bearer realm="notes"'})
                return
            if note_ref["service"] is None:
                self._json({"ok": False, "error": "notes_unavailable",
                            "message": f"笔记存储不可用：{note_ref['error']}"}, 503, cors)
                return
            # 「储存对话内容」只约束问答页自动/手动沉淀的那条路子：
            # 智能体经 MCP/API 显式 save_note 是它自己的意图，不该被这个开关连坐。
            if (method == "POST" and path.rstrip("/") == "/api/notes"
                    and isinstance(body, dict) and body.get("from") == "chat"
                    and not appconfig.store_chat()):
                self._json({"ok": False, "error": "store_chat_off",
                            "message": "已关闭「储存对话内容」，可在设置里打开后再保存"}, 403, cors)
                return
            try:
                status, payload, extra = notes_dispatch(note_ref["service"], method, path, query, body)
            except ApiError as exc:
                if method != "GET":
                    guards.audit.write(f"notes.{method.lower()}.rejected", client=self._client(),
                                       path=path[:120], error=exc.payload.get("error"))
                self._json(exc.payload, exc.status, {**cors, **exc.headers})
                return
            except Exception as exc:  # noqa: BLE001 —— 未预期异常也要回结构化错误，不能掐断连接
                traceback.print_exc()
                guards.audit.write(f"notes.{method.lower()}.error", client=self._client(),
                                   path=path[:120], error=f"{type(exc).__name__}: {exc}")
                self._json({"ok": False, "error": "internal_error",
                            "message": self._error_text(exc)}, 500, cors)
                return
            if method != "GET":
                guards.audit.write(f"notes.{method.lower()}", client=self._client(),
                                   id=payload.get("id"), duplicate_of=payload.get("duplicate_of"))
            elif (path.rstrip("/") == "/api/notes/export" and status == 200
                    and self.command == "GET"):
                # 只有真的下载了才算备份：do_HEAD 复用 do_GET，HEAD 探测会把红点骗消失
                appconfig.mark_exported()
            self._json(payload, status, {**cors, **extra})
        def _home(self) -> str:
            """存储区根目录：笔记、会话、导出都在它下面，换位置只需改一处。"""
            service = note_ref["service"]
            return str(service.store.home) if service else ""
        def _threads(self, method: str, path: str, query: dict, body: dict | None) -> None:
            """会话记录改存服务端（v1.19.0）。

            以前放 localStorage：换浏览器就没了，智能体也读不到。
            现在一条会话一个 JSON 文件放在 `<home>/threads/` 下，人和智能体看的是同一份。
            """
            cors = self._cors_headers()
            if method == "OPTIONS":
                self.send_response(204)
                for key, value in {**cors, "Allow": "GET, PUT, DELETE, OPTIONS"}.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            guard = self._notes_guard()
            if guard:
                self._json(guard, 401, {**cors, "WWW-Authenticate": 'Bearer realm="notes"'})
                return
            home = self._home()
            if not home:
                self._json({"ok": False, "error": "storage_unavailable",
                            "message": f"存储区不可用：{note_ref['error']}"}, 503, cors)
                return
            store = ThreadStore(home)
            parts = [p for p in path.strip("/").split("/") if p]  # ["api","threads",id?]
            thread_id = parts[2] if len(parts) > 2 else ""
            try:
                if method == "GET" and not thread_id:
                    limit = int((query.get("limit") or ["60"])[0])
                    items = store.list(limit=max(1, min(200, limit)))
                    self._json({"ok": True, "items": items, "count": len(items)}, 200, cors)
                    return
                if method == "GET":
                    self._json({"ok": True, "thread": store.get(thread_id)}, 200, cors)
                    return
                if method == "PUT" and thread_id:
                    meta = store.put(thread_id, body or {})
                    # 刚写的会话要立刻反映到「存储占用」里，否则用户看到的是上一次的数
                    settings_ops.invalidate_storage()
                    self._json({"ok": True, "thread": meta}, 200, cors)
                    return
                if method == "PUT" and not thread_id:
                    self._json({"ok": False, "error": "invalid_argument",
                                "message": "缺少会话 id"}, 400, cors)
                    return
                if method == "POST" and thread_id == "import":
                    copied = store.import_many((body or {}).get("threads"))
                    self._json({"ok": True, "imported": copied}, 200, cors)
                    return
                if method == "DELETE" and thread_id:
                    store.delete(thread_id)
                    settings_ops.invalidate_storage()
                    self._json({"ok": True}, 200, cors)
                    return
            except ThreadError as exc:
                self._json({"ok": False, "error": "invalid_argument", "message": str(exc)}, 400, cors)
                return
            except KeyError:
                self._json({"ok": False, "error": "not_found",
                            "message": "这条会话不在了（可能已被删除或改名）"}, 404, cors)
                return
            except OSError as exc:
                self._json({"ok": False, "error": "storage_error",
                            "message": f"存储区读写失败：{exc}"}, 500, cors)
                return
            self._json({"ok": False, "error": "not_found", "message": "接口不存在"}, 404, cors)
        def _files(self, method: str, path: str, query: dict, body: dict | None) -> None:
            """存储区里的原文读写：让「文件支持自由修改」落在页面上，而不是只写在文档里。"""
            cors = self._cors_headers()
            if method == "OPTIONS":
                self.send_response(204)
                for key, value in {**cors, "Allow": "GET, PUT, POST, OPTIONS"}.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            guard = self._notes_guard()
            if guard:
                self._json(guard, 401, {**cors, "WWW-Authenticate": 'Bearer realm="notes"'})
                return
            home = self._home()
            if not home:
                self._json({"ok": False, "error": "storage_unavailable",
                            "message": "存储区不可用"}, 503, cors)
                return
            action = path.rstrip("/").rsplit("/", 1)[-1]
            try:
                if method == "GET" and action == "raw":
                    rel = (query.get("path") or [""])[0]
                    self._json({"ok": True, **fileops.read(home, rel)}, 200, cors)
                    return
                if method == "PUT" and action == "raw":
                    data = body or {}
                    result = fileops.write(home, data.get("path"), data.get("content", ""),
                                           str(data.get("base_rev") or ""),
                                           create=bool(data.get("create")))
                    self._json({"ok": True, **result}, 200, cors)
                    return
                if method == "POST" and action == "open":
                    target = fileops.open_external(home, (body or {}).get("path"))
                    self._json({"ok": True, "opened": target}, 200, cors)
                    return
                if method == "POST" and action == "open-folder":
                    _open_folder(home)
                    self._json({"ok": True, "path": home}, 200, cors)
                    return
            except fileops.FileError as exc:
                self._json({"ok": False, "error": "file_error", "message": str(exc)},
                           exc.status, cors)
                return
            self._json({"ok": False, "error": "not_found", "message": "接口不存在"}, 404, cors)
        def _storage(self, method: str, path: str, query: dict, body: dict | None) -> None:
            """存储区整库备份 / 恢复。

            和 `/api/files/raw` 的区别：那是「改一个文件」，这里是「回到某个时间点」。
            恢复前会自动再做一份备份，避免「恢复本身变成误操作」。
            """
            cors = self._cors_headers()
            home = self._home()
            if not home:
                self._json({"ok": False, "error": "storage_unavailable",
                            "message": "存储区不可用"}, 503, cors)
                return
            action = path.rstrip("/").rsplit("/", 1)[-1]
            try:
                if method == "GET" and action == "backups":
                    self._json({"ok": True, "items": backup.list_backups(home)}, 200, cors)
                    return
                if method == "POST" and action == "backup":
                    result = backup.create(home, note=str((body or {}).get("note") or ""))
                    guards.audit.write("storage.backup", client=self._client(),
                                       name=result["name"], files=result["files"],
                                       bytes=result["bytes"])
                    self._json({"ok": True, **result}, 200, cors)
                    return
                if method == "POST" and action == "restore":
                    data = body or {}
                    result = backup.restore(home, str(data.get("name") or ""),
                                            force=bool(data.get("force")))
                    settings_ops.invalidate_storage()
                    guards.audit.write("storage.restore", client=self._client(),
                                       source=result["source"], restored=result["restored"],
                                       pre_backup=result.get("pre_backup"))
                    self._json({"ok": True, **result}, 200, cors)
                    return
            except backup.BackupError as exc:
                self._json({"ok": False, "error": "backup_error", "message": str(exc)},
                           exc.status, cors)
                return
            except OSError as exc:
                self._json({"ok": False, "error": "storage_error",
                            "message": f"存储区读写失败：{exc}"}, 500, cors)
                return
            self._json({"ok": False, "error": "not_found", "message": "接口不存在"}, 404, cors)
        def _settings(self, method: str, path: str, query: dict, body: dict | None) -> None:
            """设置面板的全部后端动作：读、改、测连接、导出/写入插件配置、打开目录。

            只允许本机或持有 ADMIN_TOKEN 的调用方修改：这里的 API Key 是明文凭据，
            不能让同一局域网里的任何人替机主决定连哪个模型。
            """
            cors = self._cors_headers()
            if method == "OPTIONS":
                self.send_response(204)
                for key, value in {**cors, "Allow": "GET, POST, OPTIONS"}.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            local = self._client() in ("127.0.0.1", "::1", "localhost")
            if method != "GET" and not local:
                token = (self.headers.get("X-Admin-Token") or "").strip()
                if not (pipe.settings.admin_token and safe_equal(token, pipe.settings.admin_token)):
                    self._json({"ok": False, "error": "forbidden",
                                "message": "设置只能在运行服务的这台电脑上修改"}, 403, cors)
                    return
            try:
                if path == "/api/settings/setup":
                    if method == "GET":
                        self._json(_setup_state(), 200, cors)
                        return
                    if method == "POST":
                        payload, status = _apply_setup(str((body or {}).get("home") or ""),
                                                       self._client())
                        self._json(payload, status, cors)
                        return
                if path == "/api/settings":
                    if method == "GET":
                        self._json(_settings_payload(), 200, cors)
                        return
                    if method == "POST":
                        before = str(note_ref["service"].store.home) if note_ref["service"] else ""
                        appconfig.update(body or {})
                        reopened = _reopen_notes()
                        payload = _settings_payload()
                        payload["notes_reloaded"] = reopened
                        after = str(note_ref["service"].store.home) if note_ref["service"] else ""
                        if before and after and os.path.normcase(before) != os.path.normcase(after):
                            count = _count_notes(before)
                            if count:
                                # 只提示不自动搬：换个空目录是常规操作，替用户决定反而吓人
                                payload["pending_migration"] = {"from": before, "count": count}
                        guards.audit.write("settings.update", client=self._client(),
                                           model=payload["llm"]["effective_model"],
                                           notes_home=payload["notes"]["home_effective"],
                                           store_chat=payload["notes"]["store_chat"])
                        self._json(payload, 200, cors)
                        return
                if path == "/api/settings/pick-folder" and method == "POST":
                    status, result = _pick_folder()
                    self._json(result, status, cors)
                    return
                if path == "/api/settings/notes/migrate" and method == "POST":
                    service = note_ref["service"]
                    if service is None:
                        self._json({"ok": False, "error": "notes_unavailable"}, 503, cors)
                        return
                    src = appconfig.clean_path(str((body or {}).get("from") or ""))
                    dst = str(service.store.home)
                    if not src or not os.path.isabs(src):
                        self._json({"ok": False, "error": "invalid_argument",
                                    "message": "需要旧位置的绝对路径"}, 400, cors)
                        return
                    if os.path.normcase(os.path.abspath(src)) == os.path.normcase(dst):
                        self._json({"ok": False, "error": "invalid_argument",
                                    "message": "新旧位置是同一个目录"}, 400, cors)
                        return
                    if not (pathlib.Path(src) / "notes").is_dir():
                        self._json({"ok": False, "error": "invalid_argument",
                                    "message": "旧位置里没有 notes 目录，没东西可搬"}, 400, cors)
                        return
                    result = _copy_notes(src, dst)
                    # 复制改的是深层子目录，指纹里的根目录 mtime 看不出变化，
                    # 这里显式作废，切回去立刻看到新位置的数字
                    settings_ops.invalidate_storage()
                    guards.audit.write("settings.notes_migrate", client=self._client(),
                                       from_path=src, to_path=dst, copied=result["copied"],
                                       skipped=result["skipped"], failed=len(result["failed"]))
                    self._json({"ok": True, "from": src, "to": dst, **result}, 200, cors)
                    return
                if path == "/api/settings/storage/clean" and method == "POST":
                    sent = body or {}
                    keep = appconfig.keep_versions()
                    if "keep" in sent:
                        try:
                            keep = max(0, int(sent.get("keep")))
                        except (TypeError, ValueError):
                            self._json({"ok": False, "error": "invalid_argument",
                                        "message": "保留版本数要是 0 或正整数"}, 400, cors)
                            return
                    # 先把选择存下来：用户点的是「按 30 版保留」，下次开机也该按 30 版
                    appconfig.update({"storage": {"keep_versions": str(keep)}})
                    service = note_ref["service"]
                    home = str(service.store.home) if service else ""
                    before = _storage_report(fresh=True)
                    removed = store.prune_versions(keep) if store is not None else []
                    # 不在这里重建索引：重建会立刻把刚删的缓存写回来，用户看到的「释放 0 B」
                    # 就是这个原因。下一次读笔记（列表或问答）时自然重建。
                    freed_index = _clear_index(home)
                    after = _storage_report(fresh=True)
                    freed = max(0, _total_bytes(before) - _total_bytes(after)) + freed_index
                    guards.audit.write("settings.storage_clean", client=self._client(),
                                       keep=keep, removed=len(removed), freed_bytes=freed)
                    self._json({"ok": True, "keep": keep, "removed": removed,
                                "freed_bytes": freed, "storage": after}, 200, cors)
                    return
                if path == "/api/settings/test" and method == "POST":
                    live = load_settings()
                    sent = body or {}
                    cfg = {
                        "base_url": str(sent.get("base_url") or live.api_base),
                        "model": str(sent.get("model") or live.model),
                        # 页面回显的是掩码；留空表示「用已保存的那把钥匙」
                        "api_key": str(sent.get("api_key") or api_key()),
                    }
                    self._json(_probe_llm(cfg), 200, cors)
                    return
                if path == "/api/settings/mcp":
                    target = _claude_config_path()
                    self._json({"ok": True, "config": _mcp_config(),
                                "target": str(target) if target else ""}, 200, cors)
                    return
                if path == "/api/settings/mcp/install" and method == "POST":
                    target = _claude_config_path()
                    if target is None:
                        self._json({"ok": False, "error": "unsupported",
                                    "message": "这个系统没有已知的 Claude Desktop 配置路径，请手动复制 JSON"}, 400, cors)
                        return
                    data: dict = {}
                    if target.exists():
                        try:
                            data = json.loads(target.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError) as exc:
                            # 不覆盖坏文件：对方自己改坏了，替它兜底会掩盖问题
                            self._json({"ok": False, "error": "bad_config",
                                        "message": f"现有配置不是合法 JSON，未改动：{exc}"}, 400, cors)
                            return
                        backup = target.with_name(target.name + f".bak-{time.strftime('%Y%m%d%H%M%S')}")
                        shutil.copy2(target, backup)
                    if not isinstance(data, dict):
                        data = {}
                    data.setdefault("mcpServers", {})["agent-notes"] = _mcp_config()["mcpServers"]["agent-notes"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    guards.audit.write("settings.mcp_install", client=self._client(), target=str(target))
                    self._json({"ok": True, "target": str(target),
                                "message": "已写入。重启 Claude Desktop 后生效"}, 200, cors)
                    return
                if path == "/api/settings/open" and method == "POST":
                    service = note_ref["service"]
                    if service is None:
                        self._json({"ok": False, "error": "notes_unavailable"}, 503, cors)
                        return
                    folder = str(service.store.home)
                    try:
                        _open_folder(folder)
                    except OSError as exc:
                        self._json({"ok": False, "error": "open_failed",
                                    "message": f"打不开文件管理器：{exc}", "path": folder}, 500, cors)
                        return
                    self._json({"ok": True, "path": folder}, 200, cors)
                    return
                self._json({"ok": False, "error": "not_found"}, 404, cors)
            except ValueError as exc:
                self._json({"ok": False, "error": "invalid_argument", "message": str(exc)}, 400, cors)
            except Exception as exc:  # noqa: BLE001 —— 设置面板报错也要能看见原因
                traceback.print_exc()
                self._json({"ok": False, "error": "internal_error",
                            "message": self._error_text(exc)}, 500, cors)

    return ResourcesRoutes
