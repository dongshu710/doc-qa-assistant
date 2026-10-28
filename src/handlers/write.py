"""写接口：问答 / 知识库 / 设置 / 评测用例。

为什么单独一层：写接口最多、也最需要逐个检查鉴权与体积上限；单独成文件便于审阅。
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


def make_write(deps):
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

    class WriteRoutes:
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

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if self._guard("POST", path):
                return
            if path.startswith("/api/storage/"):
                body, err = self._read_note_body()
                if err:
                    self._json({"ok": False, "error": "invalid_argument", "message": err}, 400)
                    return
                self._storage("POST", path, parse_qs(urlparse(self.path).query), body)
                return
            if path == "/api/settings" or path.startswith("/api/settings/"):
                body, err = self._read_note_body()
                if err:
                    self._json({"ok": False, "error": "invalid_argument", "message": err}, 400)
                    return
                self._settings("POST", path, parse_qs(urlparse(self.path).query), body)
                return
            if path == "/api/notes" or path.startswith("/api/notes/"):
                body, err = self._read_note_body()
                if err:
                    self._json({"ok": False, "error": "invalid_argument", "message": err}, 400)
                    return
                self._notes("POST", path, parse_qs(urlparse(self.path).query), body)
                return
            if path == "/api/threads" or path.startswith("/api/threads/"):
                body, err = self._read_note_body()
                if err:
                    self._json({"ok": False, "error": "invalid_argument", "message": err}, 400)
                    return
                self._threads("POST", path, parse_qs(urlparse(self.path).query), body)
                return
            if path.startswith("/api/files/"):
                body, err = self._read_note_body()
                if err:
                    self._json({"ok": False, "error": "invalid_argument", "message": err}, 400)
                    return
                self._files("POST", path, parse_qs(urlparse(self.path).query), body)
                return
            if path not in ("/api/ask", "/api/ask/stream", "/api/feedback", "/api/reload",
                            "/api/cases/from_feedback",
                            "/api/knowledge/upload", "/api/knowledge/upload_pdf",
                            "/api/knowledge/upload_file", "/api/knowledge/delete",
                            "/api/cases/from_doc", "/api/cases/run",
                            "/api/kb/approve", "/api/kb/reject", "/api/kb/rollback_doc",
                            "/api/keywords/rebuild", "/api/session/clear",
                            "/api/admin/config", "/api/admin/rollback"):
                self._json({"error": "not found"}, 404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json({"error": "invalid content-length"}, 400)
                return
            if path == "/api/knowledge/upload":
                limit = UPLOAD_MAX_BYTES
            elif path in ("/api/knowledge/upload_pdf", "/api/knowledge/upload_file"):
                limit = DOC_B64_MAX_BYTES
            else:
                limit = MAX_BODY_BYTES
            if length <= 0 or length > limit:
                self._json({"error": "body empty or too large"}, 400)
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._json({"error": "invalid json"}, 400)
                return

            if path == "/api/admin/config":
                if not self._is_admin():
                    self._json({"error": "forbidden"}, 403)
                    return
                percent = payload.get("canary_percent")
                if percent is not None:
                    try:
                        percent = max(0, min(100, int(percent)))
                    except (TypeError, ValueError):
                        self._json({"ok": False, "error": "canary_percent 需为 0-100 的整数"}, 400)
                        return
                updated = guards.runtime.update(
                    canary_percent=percent,
                    canary_model=payload.get("canary_model"),
                    note=str(payload.get("note") or "")[:200],
                )
                guards.audit.write("admin.config", client=self._client(), **updated)
                self._json({"ok": True, "runtime": updated})
                return

            if path == "/api/admin/rollback":
                if not self._is_admin():
                    self._json({"error": "forbidden"}, 403)
                    return
                res = guards.runtime.rollback()
                guards.audit.write("admin.rollback", client=self._client(),
                                   rolled_back=res.get("rolled_back"), revision=res.get("revision"))
                self._json({"ok": True, **res})
                return

            if path == "/api/knowledge/upload":
                name = _safe_kb_name(payload.get("name"))
                content = str(payload.get("content") or "")
                if not name:
                    self._json({"ok": False, "error": "只支持 .md / .txt，文件名不合法"}, 400)
                    return
                if not content.strip():
                    self._json({"ok": False, "error": "文件内容为空"}, 400)
                    return

                if store is not None:
                    try:
                        staged = store.stage({name: content}, author=self._client(),
                                             note=str(payload.get("note") or "")[:200])
                        change_id = staged["change"]["change_id"]
                        approved = None
                        total = None
                        if self._auto_approve():
                            approved = store.approve(change_id, approver=self._client(),
                                                     note="auto-approve")
                            total = reload_kb()
                    except (kbstore.KnowledgeError, ValueError) as exc:
                        self._json({"ok": False, "error": str(exc)}, 400)
                        return
                    except Exception as exc:  # noqa: BLE001
                        self._json({"ok": False, "error": f"入库失败：{exc}"}, 500)
                        return
                    self._json({
                        "ok": True, "name": name,
                        "pending": approved is None,
                        "change_id": change_id,
                        "version": store.active_version(),
                        "files": len([n for n in os.listdir(kb_dir()) if n.lower().endswith(ALLOWED_EXT)]),
                        **index_fields(),
                    })
                    guards.audit.write("kb.upload", client=self._client(), name=name, kind="text",
                                       chunks=total, chars=len(content),
                                       change_id=change_id, version=store.active_version(),
                                       auto_approved=approved is not None)
                    return

                with open(os.path.join(kb_dir(), name), "w", encoding="utf-8") as f:
                    f.write(content)
                try:
                    total = pipe.reload()
                except Exception as exc:  # noqa: BLE001
                    self._json({"ok": False, "error": f"已写入但重载失败：{exc}"}, 500)
                    return
                self._json({"ok": True, "name": name, "chunks": total,
                            "files": len([n for n in os.listdir(kb_dir()) if n.lower().endswith(ALLOWED_EXT)])})
                guards.audit.write("kb.upload", client=self._client(), name=name,
                                   kind="text", chunks=total, chars=len(content))
                return

            if path in ("/api/knowledge/upload_pdf", "/api/knowledge/upload_file"):
                name = _safe_doc_name(payload.get("name"))
                if not name:
                    self._json({"ok": False,
                                "error": "只接受纯文件名的 " + " / ".join(
                                    e.lstrip(".").upper() for e in ingest.SUPPORTED_EXT) + " 文件"}, 400)
                    return
                blob = payload.get("data_b64") or payload.get("file") or ""
                if not isinstance(blob, str) or not blob.strip():
                    self._json({"ok": False, "error": "PDF 内容为空"}, 400)
                    return
                try:
                    data = base64.b64decode(blob, validate=False)
                except (binascii.Error, ValueError):
                    self._json({"ok": False, "error": "base64 解码失败，请重试"}, 400)
                    return
                if len(data) > DOC_MAX_BYTES:
                    self._json({"ok": False,
                                "error": f"文件超过 {DOC_MAX_BYTES // 1024 // 1024} MB 上限"}, 413)
                    return
                # 文件头先校验：改后缀的假文件属于「请求有问题」（400），
                # 真文件解析失败（加密/扫描件）才是「内容不可用」（422）。
                ext = os.path.splitext(name)[1].lower()
                # csv/tsv 是纯文本，没有魔数可校验；xlsx/docx 都是 ZIP
                magic = {".pdf": b"%PDF", ".docx": b"PK", ".xlsx": b"PK"}.get(ext, b"")
                if magic and not data.startswith(magic):
                    self._json({"ok": False,
                                "error": f"不是有效的 {ext.lstrip('.').upper()} 文件（文件头不匹配）"}, 400)
                    return

                before = len(pipe.chunks)
                stage_dir = tempfile.mkdtemp(prefix="kb_stage_")
                try:
                    res = ingest.ingest_bytes(
                        data, name, stage_dir,
                        engine=os.getenv("PDF_ENGINE", "auto"),
                    )
                except Exception as exc:  # noqa: BLE001 —— 任何解析异常都要回给用户，不能 500 空响应
                    shutil.rmtree(stage_dir, ignore_errors=True)
                    self._json({"ok": False, "error": f"解析异常：{type(exc).__name__}: {exc}"}, 422)
                    return
                if not res.get("ok"):
                    shutil.rmtree(stage_dir, ignore_errors=True)
                    self._json({"ok": False, "error": res.get("error"),
                                "need_ocr": res.get("need_ocr")}, 422)
                    return

                # 原始 PDF 只在校验通过后落盘，避免失败的上传在 data/raw 里堆垃圾
                with open(os.path.join(raw_dir, name), "wb") as f:
                    f.write(data)

                md_path = os.path.join(stage_dir, res["md"])
                with open(md_path, "rb") as f:
                    md_bytes = f.read()

                if store is not None:
                    try:
                        staged = store.stage({res["md"]: md_bytes}, author=self._client(),
                                             note=f"由 {name} 解析（{res.get('engine')}）")
                        change_id = staged["change"]["change_id"]
                        approved = None
                        total = None
                        if self._auto_approve():
                            approved = store.approve(change_id, approver=self._client(),
                                                     note="auto-approve")
                            total = reload_kb()
                    except (kbstore.KnowledgeError, ValueError) as exc:
                        shutil.rmtree(stage_dir, ignore_errors=True)
                        self._json({"ok": False, "error": str(exc)}, 400)
                        return
                    except Exception as exc:  # noqa: BLE001
                        shutil.rmtree(stage_dir, ignore_errors=True)
                        self._json({"ok": False, "error": f"入库失败：{exc}"}, 500)
                        return
                    self._json({
                        "ok": True, "name": name, "md": res["md"], "chars": res["chars"],
                        "engine": res["engine"], "format": res.get("format"),
                        "pages": res.get("pages"), "paragraphs": res.get("paragraphs"),
                        "tables": res.get("tables"), "note": res.get("note"),
                        "sheets": res.get("sheets"), "rows": res.get("rows"),
                        "need_ocr": res.get("need_ocr"), "truncated": res.get("truncated"),
                        "pending": approved is None, "change_id": change_id,
                        "version": store.active_version(),
                        "files": len([n for n in os.listdir(kb_dir()) if n.lower().endswith(ALLOWED_EXT)]),
                        **index_fields(before),
                    })
                    guards.audit.write("kb.upload", client=self._client(), name=name,
                                       kind=res.get("format") or ext.lstrip("."), chunks=total,
                                       bytes=len(data), engine=res.get("engine"),
                                       change_id=change_id, version=store.active_version(),
                                       auto_approved=approved is not None)
                    shutil.rmtree(stage_dir, ignore_errors=True)
                    return

                with open(os.path.join(kb_dir(), res["md"]), "wb") as f:
                    f.write(md_bytes)
                shutil.rmtree(stage_dir, ignore_errors=True)
                try:
                    total = pipe.reload()
                except Exception as exc:  # noqa: BLE001
                    self._json({"ok": False, "error": f"已转换但索引重建失败：{exc}"}, 500)
                    return
                self._json({
                    "ok": True,
                    "name": name,
                    "md": res["md"],
                    "chars": res["chars"],
                    "engine": res["engine"],
                    "format": res.get("format"),
                    "pages": res.get("pages"),
                    "paragraphs": res.get("paragraphs"),
                    "tables": res.get("tables"),
                    "note": res.get("note"),
                    "chunks": total,
                    "added_chunks": total - before,
                    "files": len([n for n in os.listdir(kb_dir()) if n.lower().endswith(ALLOWED_EXT)]),
                })
                guards.audit.write("kb.upload", client=self._client(), name=name,
                                   kind=res.get("format") or ext.lstrip("."), chunks=total,
                                   bytes=len(data), engine=res.get("engine"))
                return

            if path == "/api/knowledge/delete":
                name = _safe_kb_name(payload.get("name"))
                target = os.path.join(kb_dir(), name) if name else ""
                if not name or not os.path.exists(target):
                    self._json({"ok": False, "error": "文件不存在"}, 404)
                    return
                remaining = [n for n in os.listdir(kb_dir()) if n.lower().endswith(ALLOWED_EXT) and n != name]
                if not remaining:
                    self._json({"ok": False, "error": "知识库至少要保留一个文件"}, 400)
                    return

                if store is not None:
                    try:
                        staged = store.stage({}, author=self._client(), deletes=[name],
                                             note=f"删除 {name}")
                        change_id = staged["change"]["change_id"]
                        approved = None
                        total = None
                        if self._auto_approve():
                            approved = store.approve(change_id, approver=self._client(),
                                                     note="auto-approve")
                            total = reload_kb()
                    except (kbstore.KnowledgeError, ValueError) as exc:
                        self._json({"ok": False, "error": str(exc)}, 400)
                        return
                    self._json({"ok": True, "name": name, "pending": approved is None,
                                "change_id": change_id, "version": store.active_version(),
                                **index_fields()})
                    guards.audit.write("kb.delete", client=self._client(), name=name,
                                       chunks=total, change_id=change_id,
                                       version=store.active_version())
                    return

                os.remove(target)
                total = pipe.reload()
                guards.audit.write("kb.delete", client=self._client(), name=name, chunks=total)
                self._json({"ok": True, "name": name, "chunks": total})
                return

            if path == "/api/kb/approve":
                if store is None or not self._is_admin():
                    self._json({"error": "forbidden"}, 403)
                    return
                change_id = str(payload.get("change_id") or "").strip()
                try:
                    res = store.approve(change_id, approver=self._client(),
                                        note=str(payload.get("note") or "")[:200])
                    total = reload_kb()
                except kbstore.KnowledgeError as exc:
                    self._json({"ok": False, "error": str(exc)}, 409)
                    return
                guards.audit.write("kb.approve", client=self._client(), change_id=change_id,
                                   version=res["version"], chunks=total)
                self._json({"ok": True, "change_id": change_id, "version": res["version"],
                            **index_fields()})
                return

            if path == "/api/kb/reject":
                if store is None or not self._is_admin():
                    self._json({"error": "forbidden"}, 403)
                    return
                change_id = str(payload.get("change_id") or "").strip()
                try:
                    res = store.reject(change_id, approver=self._client(),
                                       reason=str(payload.get("reason") or "")[:200])
                except kbstore.KnowledgeError as exc:
                    self._json({"ok": False, "error": str(exc)}, 409)
                    return
                guards.audit.write("kb.reject", client=self._client(), change_id=change_id)
                self._json({"ok": True, **res})
                return

            if path == "/api/kb/rollback_doc":
                if store is None or not self._is_admin():
                    self._json({"error": "forbidden"}, 403)
                    return
                name = str(payload.get("name") or "").strip()
                to_version = str(payload.get("to_version") or "").strip()
                try:
                    res = store.rollback_doc(name, to_version, author=self._client(),
                                             note=str(payload.get("note") or "")[:200])
                    total = reload_kb()
                except kbstore.KnowledgeError as exc:
                    self._json({"ok": False, "error": str(exc)}, 409)
                    return
                guards.audit.write("kb.rollback_doc", client=self._client(), name=name,
                                   from_version=to_version, version=res["version"], chunks=total)
                self._json({"ok": True, "name": name, "from": to_version,
                            "version": res["version"], **index_fields()})
                return

            if path == "/api/cases/from_doc":
                name = _safe_kb_name(payload.get("name"))
                if not name:
                    self._json({"ok": False, "error": "请指定知识库里的 .md 文件名"}, 400)
                    return
                doc_id = name.rsplit(".", 1)[0]
                chunks = [c for c in pipe.chunks if c.doc_id == doc_id]
                if not chunks:
                    self._json({"ok": False, "error": f"文档 {name} 没有可用的知识块"}, 404)
                    return
                try:
                    n = max(1, min(8, int(payload.get("n") or 3)))
                except (TypeError, ValueError):
                    n = 3
                res = casegen.generate_for_document(
                    doc_id, chunks, doc_cases_path, n=n,
                    prefer_llm=bool(payload.get("use_llm", True)),
                )
                if not res["added"]:
                    self._json({"ok": False, "error": res.get("reason") or "未能生成用例",
                                "mode": res.get("mode")}, 422)
                    return
                self._json({"ok": True, "doc": name, **res})
                return

            if path == "/api/cases/run":
                scope = str(payload.get("scope") or "docs")
                files = (evaluator.default_case_files() if scope == "all"
                         else ([evaluator.DOCS] if evaluator.DOCS.exists() else []))
                cases = evaluator.load_cases(files)
                if not cases:
                    self._json({"ok": True, "scope": scope, "total": 0, "passed": 0,
                                "pass_rate": 0.0, "by_category": {}, "failed": [],
                                "skipped": [], "run_at": datetime.now(timezone.utc).isoformat(),
                                "error": "没有可运行的用例"})
                    return
                try:
                    sleep_s = max(0.0, min(10.0, float(payload.get("sleep") or 0)))
                except (TypeError, ValueError):
                    sleep_s = 0.0
                started = time.time()
                results, skipped = evaluator.run_cases(
                    pipe, cases, sleep=sleep_s, skip_missing_doc=True, kb_dir=kb_dir())
                summary = evaluator.summarize(results, skipped)
                report = {
                    "run_at": datetime.now(timezone.utc).isoformat(),
                    "scope": scope,
                    "channel": pipe.settings.channel,
                    "model": pipe.settings.model,
                    **summary,
                    "duration_ms": int((time.time() - started) * 1000),
                    "results": results,
                }
                with open(run_report_path, "w", encoding="utf-8") as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)
                guards.audit.write("cases.run", client=self._client(), scope=scope,
                                   total=summary["total"], passed=summary["passed"],
                                   duration_ms=report["duration_ms"])
                self._json({
                    "ok": True,
                    "scope": scope,
                    "total": summary["total"],
                    "passed": summary["passed"],
                    "pass_rate": summary["pass_rate"],
                    "by_category": summary["by_category"],
                    "skipped": summary["skipped"],
                    "failed": [{"id": r["id"], "input": r["input"], "failures": r["failures"]}
                               for r in results if not r["passed"]],
                    "duration_ms": report["duration_ms"],
                    "run_at": report["run_at"],
                })
                return

            if path == "/api/feedback":
                # no_answer 的反馈比正答更有价值：它直接告诉我们要补哪份资料。
                # 因此除了「有用/没用」，还收「期望答案」与「缺失文档」两个字段。
                record = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "trace_id": str(payload.get("trace_id", ""))[:64],
                    "useful": bool(payload.get("useful")),
                    "comment": str(payload.get("comment", ""))[:500],
                    "behavior": str(payload.get("behavior") or "")[:32],
                    "query": str(payload.get("query") or "")[:300],
                    "expected": str(payload.get("expected") or "")[:500],
                    "document": str(payload.get("document") or "")[:200],
                    "session_id": str(payload.get("session_id") or "")[:64],
                    "kb_version": str(payload.get("kb_version") or "")[:32],
                }
                jsonl.append_line(feedback_path, json.dumps(record, ensure_ascii=False),
                                  int(pipe.settings.log_max_bytes),
                                  int(pipe.settings.log_keep))
                guards.audit.write("feedback", client=self._client(), trace_id=record["trace_id"],
                                   useful=record["useful"], behavior=record["behavior"],
                                   has_expected=bool(record["expected"]),
                                   document=record["document"])
                self._json({"ok": True, "need": not record["useful"]})
                return

            if path == "/api/keywords/rebuild":
                if not self._is_admin():
                    self._json({"error": "forbidden"}, 403)
                    return
                try:
                    detail = pipe.rebuild_keywords(enrich=True)
                    guards.audit.write("keywords.rebuild", client=self._client(),
                                       entries=detail.get("entries"), llm=detail.get("llm"))
                    self._json({"ok": True, "keywords": detail,
                                "summary": pipe.keywords.summary()})
                except Exception as exc:  # noqa: BLE001
                    self._json({"ok": False, "error": str(exc)}, 500)
                return

            if path == "/api/session/clear":
                sid = str(payload.get("session_id") or "").strip()[:64]
                pipe.sessions.clear(sid)
                self._json({"ok": True, "session_id": sid, "sessions": pipe.sessions.status()})
                return

            if path == "/api/reload":
                try:
                    total = reload_kb()
                    guards.audit.write("kb.reload", client=self._client(), chunks=total)
                    self._json({"ok": True, **index_fields()})
                except Exception as exc:  # noqa: BLE001
                    self._json({"ok": False, "error": str(exc)}, 500)
                return

            if path == "/api/cases/from_feedback":
                trace_id = str(payload.get("trace_id", ""))
                rows = list(reversed(_read_jsonl(pipe.log_path, 5000)))
                query = next((r.get("query", "") for r in rows if r.get("trace_id") == trace_id), "")
                if not query:
                    self._json({"ok": False, "error": "未找到该 trace 对应的问题"}, 400)
                    return
                keywords = [str(k).strip() for k in (payload.get("keywords") or []) if str(k).strip()]
                behavior = str(payload.get("behavior") or "answer")
                note = str(payload.get("note") or "")[:200]
                existing = _read_jsonl(feedback_cases_path, 100000)
                seq = len(existing) + 1
                case_id = f"F{seq:03d}"
                expect = {"behavior": behavior}
                if keywords:
                    expect["output_contains"] = keywords
                case = {
                    "id": case_id,
                    "category": "regression",
                    "input": query,
                    "expect": expect,
                    "source": "feedback",
                    "source_trace": trace_id,
                    "note": note,
                }
                os.makedirs(os.path.dirname(feedback_cases_path), exist_ok=True)
                with open(feedback_cases_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(case, ensure_ascii=False) + "\n")
                self._json({"ok": True, "case": case, "total": seq})
                return

            if path == "/api/ask/stream":
                pre, err = self._ask_preflight(payload)
                if err:
                    body, code, headers = err
                    self._json(body, code, extra_headers=headers)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True

                def send(event: str, data: dict) -> None:
                    chunk = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()

                def send_comment(text: str) -> None:
                    # SSE 注释行：心跳，客户端会忽略，但代理与浏览器知道连接还活着
                    self.wfile.write(f": {text}\n\n".encode("utf-8"))
                    self.wfile.flush()

                if pre["cached"] is not None:
                    metrics.inc("rag_idempotent_replay_total")
                    guards.audit.write("ask.idempotent_replay", client=pre["client"],
                                       key=pre["idem_key"],
                                       trace_id=pre["cached"].get("trace_id"),
                                       request_id=pre["request_id"])
                    send("final", pre["cached"])
                    return

                started = time.time()
                events: queue.Queue = queue.Queue()
                # 生成放到独立线程：主线程要能在「模型还没吐第一个字」时发心跳，
                # 否则浏览器/代理会以为连接死了，而实际只是检索慢或模型排队。
                def produce() -> None:
                    try:
                        for item in pipe.ask_stream(
                                pre["query"], model=pre["model"],
                                force_extractive=pre["budget_blocked"],
                                session_id=pre["session_id"]):
                            events.put(item)
                    except Exception as exc:  # noqa: BLE001 —— 生成线程的异常要回传给请求线程
                        events.put(("__error__", str(exc)[:300]))
                    finally:
                        events.put(("__done__", None))

                threading.Thread(target=produce, name="ask-stream", daemon=True).start()
                try:
                    send_comment("connected")
                    while True:
                        if time.time() - started > SSE_MAX_SECONDS:
                            send("error", {"error": f"回答超过 {int(SSE_MAX_SECONDS)} 秒，已中断"})
                            break
                        try:
                            event, data = events.get(timeout=SSE_HEARTBEAT_S)
                        except queue.Empty:
                            send_comment("ping")
                            continue
                        if event == "__done__":
                            break
                        if event == "__error__":
                            send("error", {"error": data})
                            break
                        if event == "delta":
                            send("delta", {"text": data})
                        elif event == "replace":
                            send("replace", {"text": data})
                        elif event == "final":
                            self._annotate_result(data, pre)
                            self._record_ask(data, pre, started, "/api/ask/stream")
                            send("final", data)
                except (BrokenPipeError, ConnectionResetError):
                    return
                return

            pre, err = self._ask_preflight(payload)
            if err:
                body, code, headers = err
                self._json(body, code, extra_headers=headers)
                return
            if pre["cached"] is not None:
                metrics.inc("rag_idempotent_replay_total")
                guards.audit.write("ask.idempotent_replay", client=pre["client"],
                                   key=pre["idem_key"],
                                   trace_id=pre["cached"].get("trace_id"),
                                   request_id=pre["request_id"])
                self._json(pre["cached"], extra_headers={"X-Idempotent-Replay": "true",
                                                          "X-Request-Id": pre["request_id"]})
                return

            started = time.time()
            result = pipe.ask(pre["query"], model=pre["model"],
                              force_extractive=pre["budget_blocked"],
                              session_id=pre["session_id"])
            self._annotate_result(result, pre)
            self._record_ask(result, pre, started, "/api/ask")
            self._json(result, extra_headers={
                "X-RateLimit-Remaining": pre["decision"].remaining,
                "X-Retrieval": str(result.get("retrieval_mode") or pipe.settings.retrieval),
                "X-Request-Id": pre["request_id"],
                "X-Answer-Path": str(result.get("path") or "rag"),
            })

        # HEAD 复用 GET 的路由：_send 已经按 command 跳过响应体。
        # 不实现会返回 501，而 HTTP/1.1 的监控探针与部分代理默认先发 HEAD。
        def _ask_preflight(self, payload: dict):
            """问答前置：鉴权、限流、幂等、灰度与预算。JSON 与流式共用，避免两套口径。"""
            query = str(payload.get("query", ""))
            session_id = str(payload.get("session_id") or "").strip()[:64] or None
            client = self._client()
            request_id = (self.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]).strip()[:64]

            key_name, auth_err = self._api_auth()
            if auth_err:
                metrics.inc("rag_unauthorized_total")
                metrics.inc("rag_http_requests_total", {"path": "/api/ask", "code": "401"})
                guards.audit.write("ask.unauthorized", client=client, query=query[:200],
                                   reason=auth_err, key=api_keys.mask(self._presented_key()),
                                   request_id=request_id)
                return None, ({
                    "error": "unauthorized",
                    "message": "需要 API Key：Authorization: Bearer <key> 或 X-API-Key",
                    "request_id": request_id,
                }, 401, {"WWW-Authenticate": 'Bearer realm="rag"', "X-Request-Id": request_id})

            # 配了 Key 就按 Key 限流与计成本；未配置时退回按 IP（本机/内网场景）
            identity = f"key:{key_name}" if key_name else client
            decision = guards.rate.allow(identity)
            if not decision.allowed:
                metrics.inc("rag_rate_limited_total")
                metrics.inc("rag_http_requests_total", {"path": "/api/ask", "code": "429"})
                guards.audit.write("ask.rate_limited", client=client, query=query[:200],
                                   retry_after=decision.retry_after, request_id=request_id,
                                   api_key=key_name)
                return None, ({"error": "rate limited", "retry_after": decision.retry_after,
                               "request_id": request_id}, 429,
                              {"Retry-After": decision.retry_after, "X-Request-Id": request_id})
            idem_key = (self.headers.get("Idempotency-Key")
                        or str(payload.get("request_id") or "")).strip()
            return {
                "query": query, "session_id": session_id, "client": client,
                "api_key": key_name, "identity": identity,
                "request_id": request_id, "decision": decision, "idem_key": idem_key,
                "cached": guards.idem.get(idem_key),
                "model": guards.runtime.pick_model(f"{identity}|{query}"),
                "budget_blocked": guards.cost.blocked,
            }, None
        def _annotate_result(self, result: dict, pre: dict) -> None:
            kb_version = store.active_version() if store is not None else None
            result["kb_version"] = kb_version
            for citation in result.get("citations") or []:
                citation.setdefault("version", kb_version)
            result["canary"] = bool(pre["model"])
            result["budget_blocked"] = pre["budget_blocked"]
            result["request_id"] = pre["request_id"]
        def _record_ask(self, result: dict, pre: dict, started: float, path_label: str) -> None:
            llm_tokens = int((result.get("usage") or {}).get("total_tokens") or 0)
            embed_tokens = int(result.get("embedding_tokens") or 0)
            tokens = llm_tokens + embed_tokens
            price = float(getattr(pipe.settings, "token_price_per_1k", 0) or 0)
            cost_usd = round(tokens / 1000 * price, 6) if price > 0 else 0.0
            result["cost_usd"] = cost_usd
            guards.cost.add(tokens)
            guards.idem.put(pre["idem_key"], result)

            behavior = str(result.get("behavior") or "unknown")
            mode = str(result.get("mode") or "none")
            answer_path = str(result.get("path") or "rag")
            metrics.inc("rag_ask_total", {"behavior": behavior, "mode": mode})
            metrics.inc("rag_answer_path_total", {"path": answer_path})
            if answer_path == "keyword":
                metrics.inc("rag_keyword_hit_total")
            for item in result.get("keyword_rejected") or []:
                metrics.inc("rag_keyword_rejected_total",
                            {"reason": str(item.get("reason") or "unknown")})
            if result.get("keyword_gate"):
                metrics.inc("rag_keyword_gate_total", {"gate": str(result["keyword_gate"])})
            if not result.get("api_called"):
                metrics.inc("rag_local_answer_total")
            metrics.inc("rag_http_requests_total", {"path": path_label, "code": "200"})
            metrics.observe("rag_ask_duration_seconds",
                            result.get("latency_ms", 0) / 1000.0 or (time.time() - started))
            metrics.inc("rag_tokens_total", {"kind": "llm"}, llm_tokens)
            metrics.inc("rag_tokens_total", {"kind": "embedding"}, embed_tokens)
            if cost_usd:
                metrics.inc("rag_cost_usd_total", value=cost_usd)
            if pre.get("api_key"):
                # 标签只放名字的哈希前缀：指标导出后可能被采集/转发，别把密钥名也带走
                key_label = hashlib.sha256(str(pre["api_key"]).encode("utf-8")).hexdigest()[:8]
                metrics.inc("rag_api_tokens_total", {"key": key_label}, tokens)
                if cost_usd:
                    metrics.inc("rag_api_cost_usd_total", {"key": key_label}, value=cost_usd)
            if result.get("degraded"):
                metrics.inc("rag_retrieval_degraded_total",
                            {"reason": str(result.get("degrade_reason") or "unknown")})
            # 引用支持度：编号合法但内容对不上时单独计数，别和「无出处」混在一起
            bad_citations = sum(1 for item in (result.get("citation_support") or [])
                                if not item.get("supported"))
            if bad_citations:
                metrics.inc("rag_citation_unsupported_total", value=bad_citations)

            guards.audit.write(
                "ask", client=pre["client"], query=pre["query"][:200],
                trace_id=result.get("trace_id"), request_id=pre["request_id"],
                behavior=behavior, mode=mode, session_id=pre["session_id"],
                retrieval_score=result.get("retrieval_score"), model=result.get("model"),
                canary=bool(pre["model"]), budget_blocked=pre["budget_blocked"], tokens=tokens,
                llm_tokens=llm_tokens, embedding_tokens=embed_tokens, cost_usd=cost_usd,
                latency_ms=result.get("latency_ms"), path=answer_path,
                api_called=bool(result.get("api_called")),
                citation_support_rate=result.get("citation_support_rate"),
                keyword_terms=result.get("keyword_terms"),
                keyword_gate=result.get("keyword_gate"),
                keyword_rejected=[f"{r.get('term')}:{r.get('reason')}"
                                  for r in (result.get("keyword_rejected") or [])],
                stream=path_label.endswith("/stream"),
                api_key=pre.get("api_key"),
            )

    return WriteRoutes
