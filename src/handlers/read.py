"""只读接口：页面 + 查询类 API。

为什么单独一层：读接口全部无副作用，和写接口混在一起最容易把「顺手写点东西」带进来。
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


def make_read(deps):
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
    _mcp_targets = deps._mcp_targets
    _picker_command = deps._picker_command
    _pick_folder = deps._pick_folder
    _count_notes = deps._count_notes
    _copy_notes = deps._copy_notes

    class ReadRoutes:
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

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            if self._guard("GET", path):
                return

            if path == "/mcp":
                # 本实现是无状态的 JSON-RPC，不提供 SSE 下行流；明确告诉客户端别试
                self._json({"error": "method_not_allowed",
                            "message": "MCP 走 POST /mcp（JSON-RPC），不支持 GET 长连接"},
                           405, {"Allow": "POST", **(self._cors_headers() or {})})
                return

            if path == "/tools.json":
                host = self.headers.get("Host") or "127.0.0.1"
                self._json(notes_tools_payload(__version__, f"http://{host}"))
                return
            if path == "/api/update/check":
                # 只查不装：返回版本号与下载地址，本地文件一个字节都不动
                force = (qs.get("force") or ["0"])[0].lower() in ("1", "true", "yes")
                self._json(update_mod.check(__version__, _repo_url(), force=force),
                           200, self._cors_headers())
                return
            if path == "/api/notes" or path.startswith("/api/notes/"):
                self._notes("GET", path, qs, None)
                return
            if path == "/api/threads" or path.startswith("/api/threads/"):
                self._threads("GET", path, qs, None)
                return
            if path.startswith("/api/files/"):
                self._files("GET", path, qs, None)
                return
            if path.startswith("/api/storage/"):
                self._storage("GET", path, qs, None)
                return
            if path == "/api/settings" or path.startswith("/api/settings/"):
                self._settings("GET", path, qs, None)
                return
            if path in ("/", "/index.html", "/insights", "/dashboard", "/report"):
                # 只留问答与知识库两页，旧入口统一回落到问答页，收藏夹不会 404
                self._redirect("/ask")
            elif path == "/ask":
                self._send(200, ASK_HTML, "text/html; charset=utf-8")
            elif path == "/files":
                # 能被收藏、能被智能体直接打开的固定地址：加不进客户端工具栏时用这个
                self._send(200, FILES_PAGE, "text/html; charset=utf-8")
            elif path == "/kb":
                self._send(200, KB_HTML, "text/html; charset=utf-8")
            elif path == "/api/l3":
                l3_path = os.path.join(project_root, "tests", "report_l3.json")
                if not os.path.exists(l3_path):
                    self._json({"available": False})
                else:
                    with open(l3_path, encoding="utf-8") as f:
                        d = json.load(f)
                    self._json({
                        "available": True,
                        "judged_at": d.get("judged_at"),
                        "judge_channel": d.get("judge_channel"),
                        "judge_model": d.get("judge_model"),
                        "answer_cases": d.get("answer_cases"),
                        "safety_cases": d.get("safety_cases"),
                        "avg": d.get("avg"),
                        "pass_rate": d.get("pass_rate"),
                        "safety_compliant_rate": d.get("safety_compliant_rate"),
                        "hallucinations": len(d.get("hallucinations") or []),
                        "gate": d.get("gate"),
                    })
            elif path == "/openapi.json":
                self._json(build_spec(__version__, api_keys.describe(),
                                      pipe.settings.model, pipe.settings.retrieval))
            elif path == "/api/health":
                if store is not None:
                    metrics.set_gauge("rag_kb_version", 1, {"version": store.active_version()})
                metrics.set_gauge("rag_index_chunks", len(pipe.chunks))
                self._json({
                    "status": "ok",
                    "version": __version__,
                    "channel": pipe.settings.channel,
                    "model": pipe.settings.model,
                    "llm_ready": pipe.llm_ready,
                    "chunks": len(pipe.chunks),
                    "retrieval": pipe.settings.retrieval,
                    "retrieval_detail": pipe.retrieval_detail,
                    "kb": store.status() if store is not None else {"enabled": False},
                    "keywords": pipe.keyword_detail,
                    "sessions": pipe.sessions.status(),
                    "guards": guards.status(),
                    "index": index_payload(),
                    "auth": api_keys.describe(),
                    "runtime": {
                        # 明确告诉使用者：这是单实例内存态，不是集群
                        "mode": "single-instance",
                        "state_backend": guards.backend,
                        "warnings": _runtime_warnings(),
                    },
                })
            elif path == "/metrics":
                # 指标带 key 标签与成本口径：不设防等于把用量结构公开给任何本机页面
                if not self._is_admin():
                    self._json({"error": "forbidden"}, 403)
                    return
                self._send(200, metrics.render(), "text/plain; version=0.0.4; charset=utf-8")
            elif path == "/api/admin/config":
                if not self._is_admin():
                    self._json({"error": "forbidden"}, 403)
                    return
                self._json({
                    "ok": True,
                    "runtime": guards.runtime.status(),
                    "model": pipe.settings.model,
                    "retrieval": pipe.settings.retrieval,
                })
            elif path == "/api/admin/cost":
                if not self._is_admin():
                    self._json({"error": "forbidden"}, 403)
                    return
                self._json({"ok": True, "cost": guards.cost.status()})
            elif path == "/api/audit":
                if not self._is_admin():
                    self._json({"error": "forbidden"}, 403)
                    return
                try:
                    limit = max(1, min(200, int(qs.get("limit", ["20"])[0])))
                except (TypeError, ValueError):
                    limit = 20
                self._json({"items": guards.audit.tail(limit)})
            elif path == "/api/metrics":
                self._json(summarize(pipe.log_path))
            elif path == "/api/cases":
                curated = _read_jsonl(os.path.join(project_root, "tests", "eval_cases.jsonl"), 100000)
                fb_cases = _read_jsonl(feedback_cases_path, 100000)
                doc_cases = _read_jsonl(doc_cases_path, 100000)
                last_run = None
                if os.path.exists(run_report_path):
                    with open(run_report_path, encoding="utf-8") as f:
                        rep = json.load(f)
                    last_run = {k: rep.get(k) for k in
                                ("run_at", "scope", "total", "passed", "pass_rate", "channel", "model")}
                self._json({
                    "curated": len(curated),
                    "feedback": len(fb_cases),
                    "docs": len(doc_cases),
                    "total": len(curated) + len(fb_cases) + len(doc_cases),
                    "doc_items": [{
                        "id": c.get("id"),
                        "input": c.get("input"),
                        "doc_id": c.get("doc_id"),
                        "generated_by": c.get("generated_by"),
                        "keywords": (c.get("expect") or {}).get("output_contains", []),
                    } for c in doc_cases[-20:]],
                    "last_run": last_run,
                })
            elif path == "/api/examples":
                try:
                    n = max(1, min(8, int(qs.get("n", ["4"])[0])))
                except (TypeError, ValueError):
                    n = 4
                # 新上传的文档优先出现在示例里：按文件 mtime 倒序排 doc
                mtimes = {}
                if os.path.isdir(kb_dir()):
                    for name in os.listdir(kb_dir()):
                        if name.lower().endswith(ALLOWED_EXT):
                            try:
                                mtimes[name.rsplit(".", 1)[0]] = os.path.getmtime(os.path.join(kb_dir(), name))
                            except OSError:
                                pass
                ordered = sorted(pipe.chunks, key=lambda c: (-mtimes.get(c.doc_id, 0), c.doc_id))
                self._json({"items": suggest.examples(ordered, n)})
            elif path == "/api/knowledge":
                counts = Counter(c.doc_id for c in pipe.chunks)
                files = []
                if os.path.isdir(kb_dir()):
                    for name in sorted(os.listdir(kb_dir())):
                        if name.lower().endswith(ALLOWED_EXT):
                            path = os.path.join(kb_dir(), name)
                            files.append({
                                "name": name,
                                "chunks": counts.get(name.rsplit(".", 1)[0], 0),
                                "size": os.path.getsize(path),
                                "mtime": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M"),
                            })
                self._json({
                    "files": [
                        {**f,
                         "keywords": pipe.keywords.top_terms(f["name"].rsplit(".", 1)[0], 5),
                         "keyword_count": len(pipe.keywords.top_terms(
                             f["name"].rsplit(".", 1)[0], 999))}
                        for f in files
                    ],
                    "total_chunks": len(pipe.chunks),
                    "rebuilding": bool(pipe.rebuild_state().get("rebuilding")),
                    "version": store.active_version() if store is not None else None,
                    "pending_changes": store.status()["pending_changes"] if store is not None else 0,
                    "keywords": pipe.keywords.summary(),
                })
            elif path == "/api/keywords":
                name = _safe_kb_name((qs.get("name") or [""])[0])
                if name:
                    doc_id = name.rsplit(".", 1)[0]
                    if doc_id not in pipe.keywords.docs:
                        self._json({"error": "文档不存在或未生成关键词"}, 404)
                        return
                    self._json(pipe.keywords.doc_view(doc_id))
                    return
                self._json({
                    "summary": pipe.keywords.summary(),
                    "docs": [
                        {"doc_id": doc_id, "title": meta.get("title") or doc_id,
                         "count": sum(1 for e in pipe.keywords.entries if e.doc_id == doc_id),
                         "terms": pipe.keywords.top_terms(doc_id, 8)}
                        for doc_id, meta in pipe.keywords.docs.items()
                    ],
                })
            elif path == "/api/kb/versions":
                if store is None:
                    self._json({"error": "KB_STORE=off，当前未启用版本库"}, 400)
                    return
                self._json({"active": store.active_version(), "items": store.versions()})
            elif path == "/api/kb/change":
                if store is None:
                    self._json({"error": "KB_STORE=off，当前未启用版本库"}, 400)
                    return
                change_id = (qs.get("id") or [""])[0].strip()
                try:
                    self._json(store.change_detail(change_id))
                except kbstore.KnowledgeError as exc:
                    self._json({"error": str(exc)}, 404)
            elif path == "/api/kb/changes":
                if store is None:
                    self._json({"error": "KB_STORE=off，当前未启用版本库"}, 400)
                    return
                status = (qs.get("status", [""])[0] or "").strip() or None
                self._json({"items": store.changes(status)})
            elif path == "/api/kb/doc_history":
                if store is None:
                    self._json({"error": "KB_STORE=off，当前未启用版本库"}, 400)
                    return
                name = (qs.get("name", [""])[0] or "").strip()
                try:
                    self._json({"name": name, "items": store.doc_history(name)})
                except kbstore.KnowledgeError as exc:
                    self._json({"error": str(exc)}, 400)
            elif path == "/api/source":
                doc = (qs.get("doc") or [""])[0]
                try:
                    chunk_index = int((qs.get("chunk") or ["-1"])[0])
                except (TypeError, ValueError):
                    chunk_index = -1
                src = pipe.source_chunk(doc, chunk_index)
                if not src:
                    self._json({"error": "原文不存在或索引已更新"}, 404)
                    return
                src["version"] = store.active_version() if store is not None else None
                self._json(src)
            elif path == "/api/feedback/list":
                limit = int(qs.get("limit", ["20"])[0])
                self._json({"items": list(reversed(_read_jsonl(feedback_path, limit)))})
            elif path == "/api/trace":
                limit = int(qs.get("limit", ["20"])[0])
                rows = list(reversed(_read_jsonl(pipe.log_path, limit)))
                items = [{
                    "ts": r.get("ts"),
                    "query": r.get("query"),
                    "behavior": r.get("behavior"),
                    "mode": r.get("mode"),
                    "latency_ms": r.get("latency_ms"),
                    "channel": r.get("channel"),
                } for r in rows]
                self._json({"items": items})
            else:
                self._json({"error": "not found"}, 404)

    return ReadRoutes
