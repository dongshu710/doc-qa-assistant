"""最小可用 Web 服务：四页（首页 / 问答 / 知识库 / 数据中心）+ HTTP API。

  python -m src.server --port 8000

路由：
  GET  /                 首页
  GET  /ask              问答（流式输出/引用原文/多轮追问/反馈）
  GET  /kb               知识库（上传/检索/出题/删除）
  GET  /insights         数据中心（概览/质量/用例/反馈/日志/汇报，可收起侧栏）
  GET  /dashboard        302 → /insights#p-overview（旧入口）
  GET  /report           302 → /insights#p-report（旧入口）
  GET  /api/health       端点 / 模型 / 检索详情 / 知识库版本 / 防护状态 / 索引重建状态
  GET  /openapi.json     OpenAPI 3.0 契约（含鉴权方案与检索配置）
  GET  /metrics          Prometheus 文本指标
  GET  /api/examples     按当前知识库生成示例问题
  GET  /api/metrics      业务聚合指标
  GET  /api/knowledge    知识库文件、块数、每份文档的关键词与活动版本
  GET  /api/keywords     关键词总览；带 name= 时返回单文档条目与摘要
  GET  /api/kb/versions  版本列表
  GET  /api/kb/changes   变更审批记录
  GET  /api/kb/change?id=... 待审批变更的文本 diff
  GET  /api/kb/doc_history?name=... 单文档版本历史
  GET  /api/source?doc=...&chunk=... 引用原文（按知识块定位）
  GET  /api/feedback/list?limit=20
  GET  /api/trace?limit=20
  GET  /api/audit?limit=20       审计日志（需 admin）
  GET  /api/admin/config         灰度配置（需 admin）
  GET  /api/admin/cost           成本上限状态（需 admin）
  POST /api/ask          {"query","session_id"}；支持 Idempotency-Key
  POST /api/ask/stream   同上，SSE 流式（delta / replace / final）
  POST /api/session/clear {"session_id"} 清空会话上下文
  POST /api/feedback     {"trace_id","useful","comment"}
  POST /api/reload       重新加载知识库
  POST /api/keywords/rebuild {} 重建关键词（接入 API 时整理变更文档，需 admin）
  POST /api/admin/config {"canary_percent","canary_model"} 调整灰度（需 admin）
  POST /api/admin/rollback {} 回滚上一版配置（需 admin）
  POST /api/kb/approve   {"change_id"} 审批并生成新版本（需 admin）
  POST /api/kb/reject    {"change_id","reason"} 拒绝变更（需 admin）
  POST /api/kb/rollback_doc {"name","to_version"} 按文档回滚（需 admin）
  POST /api/knowledge/upload      {"name","content"} 上传 .md/.txt
  POST /api/knowledge/upload_file {"name","data_b64"} 上传 PDF/DOCX（服务端解析成 Markdown）
  POST /api/knowledge/upload_pdf  同上（兼容旧名）
  POST /api/cases/from_doc        {"name","n"} 为某份文档自动生成评测用例
  POST /api/cases/run             {"scope":"docs"|"all"} 跑用例并回传结果
  POST /api/knowledge/delete      {"name"} 删除知识库文件
"""
import argparse
import base64
import binascii
import gzip
import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import casegen, evaluator, ingest, jsonl, kbstore, suggest
from .auth import ApiKeyStore
from .config import load_settings
from .guards import Guards
from .insights import render as render_insights
from .metrics import summarize
from .metrics_exporter import Metrics
from .openapi import build_spec
from .pipeline import RAGPipeline
from .report import collect as collect_report
from .report import render as render_report
from .version import __version__
from .web_pages import ASK_HTML, HOME_HTML, KB_HTML

MAX_BODY_BYTES = 8192
UPLOAD_MAX_BYTES = 512 * 1024          # 单个文本文件上限（.md/.txt）
DOC_MAX_BYTES = 6 * 1024 * 1024         # 单个 PDF/DOCX 上限（解码后）
DOC_B64_MAX_BYTES = DOC_MAX_BYTES * 4 // 3 + 4096
ALLOWED_EXT = (".md", ".txt")


def _safe_kb_name(name) -> str | None:
    """只接受「纯文件名」的 .md/.txt。

    显式拒绝路径分隔符而不是 basename 静默改名：
    静默改名虽然安全，但会让用户以为传了 `../x.md` 却出现 `x.md`，属于隐性行为。
    """
    raw = str(name or "").strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw:
        return None
    if len(raw) > 80 or not raw.lower().endswith(ALLOWED_EXT):
        return None
    if any(ch in raw for ch in '<>:"|?*\x00'):
        return None
    return raw


def _knowledge_dir() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data", "knowledge")


def _raw_dir() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "data", "raw")
    os.makedirs(path, exist_ok=True)
    return path


def _safe_doc_name(name) -> str | None:
    """上传文档名：只接受纯文件名，且扩展名必须在 `ingest.SUPPORTED_EXT` 内。"""
    raw = str(name or "").strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw:
        return None
    if len(raw) > 120 or not raw.lower().endswith(ingest.SUPPORTED_EXT):
        return None
    if any(ch in raw for ch in '<>:"|?*\x00'):
        return None
    return raw


def _read_jsonl(path: str, limit: int) -> list[dict]:
    """尾部 N 条（旧 → 新）；调用方按需 reverse。"""
    return jsonl.tail_json(path, max(1, int(limit)))


def create_server(host: str, port: int, knowledge_dir: str | None = None):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    settings = load_settings()
    metrics = Metrics(enabled=True)

    # 显式传入目录 = 传统单目录模式（测试与批量导入用）；否则走版本库 + 审批流
    store: kbstore.KnowledgeStore | None = None
    if knowledge_dir is None and settings.kb_store not in ("off", "0", "false", "no"):
        kb_root = settings.kb_dir if os.path.isabs(settings.kb_dir) else os.path.join(project_root, settings.kb_dir)
        seed = settings.kb_seed_dir if os.path.isabs(settings.kb_seed_dir) else os.path.join(project_root, settings.kb_seed_dir)
        store = kbstore.KnowledgeStore(kb_root, seed_dir=seed,
                                       keep_versions=settings.kb_keep_versions)
        store.bootstrap()
        pipe = RAGPipeline(store.active_dir())
    else:
        pipe = RAGPipeline(knowledge_dir or _knowledge_dir())

    log_dir = os.path.dirname(pipe.log_path)
    guards = Guards(pipe.settings, log_dir)
    api_keys = ApiKeyStore(pipe.settings.api_keys)
    feedback_path = os.path.join(log_dir, "feedback.jsonl")
    feedback_cases_path = os.path.join(project_root, "tests", "eval_cases_feedback.jsonl")
    raw_dir = _raw_dir()
    doc_cases_path = os.path.join(project_root, "tests", "eval_cases_docs.jsonl")
    run_report_path = os.path.join(project_root, "tests", "report_doc_cases.json")

    def kb_dir() -> str:
        """活动版本目录；审批通过后只换这个指针，不在原目录上打补丁。"""
        # 异步重建期间 pipe.knowledge_dir 还是旧的，列表必须以版本库为准，
        # 否则刚上传的文件在页面上“消失”几秒。
        return store.active_dir() if store is not None else pipe.knowledge_dir

    def async_reload() -> bool:
        # 传统单目录模式（测试/批量导入）保持同步：调用方拿到的 chunks 必须是最终值。
        return store is not None and (pipe.settings.kb_async_reload or "on").strip().lower() == "on"

    def reload_kb(wait: bool | None = None) -> int | None:
        """重建索引。默认按 KB_ASYNC_RELOAD 走后台；返回 None 表示“已排队”。"""
        target = store.active_dir() if store is not None else None
        if wait is None:
            wait = not async_reload()
        if wait:
            return pipe.reload(target or pipe.knowledge_dir)
        pipe.reload_async(target or pipe.knowledge_dir)
        return None

    def index_payload() -> dict:
        return pipe.rebuild_state()

    def index_fields(before: int | None = None) -> dict:
        """接口响应用的索引字段：重建中时 chunks 返回 null，避免报旧值误导。"""
        state = pipe.rebuild_state()
        building = bool(state.get("rebuilding"))
        out = {"rebuilding": building, "index": state,
               "chunks": None if building else len(pipe.chunks)}
        if before is not None:
            out["added_chunks"] = None if building else len(pipe.chunks) - before
        return out

    class Handler(BaseHTTPRequestHandler):
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

        def _send(self, code: int, body: str, content_type: str = "application/json; charset=utf-8",
                  extra_headers: dict | None = None, cache: str = "no-cache") -> None:
            """统一出口：gzip + ETag 协商 + 定长。

            页面用 `cache="no-cache"`：可以存，但每次要带 ETag 回源校验，
            内容没变就回 304（约 150 字节），部署后也不会拿到旧页面。
            JSON 接口用 `no-store`，避免中间层缓存掉一次问答结果。
            """
            data = body.encode("utf-8")
            extra = {key: str(value) for key, value in (extra_headers or {}).items()}
            # 弱校验：gzip 后字节不同但内容相同，仍应命中同一个 ETag
            etag = 'W/"' + hashlib.sha256(data).hexdigest()[:20] + '"'
            headers = {"ETag": etag, "Cache-Control": cache, "Vary": "Accept-Encoding"}

            inm = (self.headers.get("If-None-Match") or "").strip()
            if inm and inm.replace("W/", "") == etag.replace("W/", ""):
                self.send_response(304)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                return

            mime = content_type.split(";")[0].strip().lower()
            accepts = (self.headers.get("Accept-Encoding") or "").lower()
            if "gzip" in accepts and mime in self.COMPRESSIBLE and len(data) >= 512:
                data = gzip.compress(data, 6)
                headers["Content-Encoding"] = "gzip"

            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            for key, value in headers.items():
                self.send_header(key, value)
            for key, value in extra.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    self.close_connection = True

        def _json(self, obj, code: int = 200, extra_headers: dict | None = None) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False), extra_headers=extra_headers,
                       cache="no-store")

        def _redirect(self, location: str, code: int = 302) -> None:
            """旧页面入口保留 302：书签与外部链接不 404，但不重复渲染两份内容。"""
            self.send_response(code)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def _client(self) -> str:
            return self.client_address[0] if self.client_address else "unknown"

        def _is_admin(self) -> bool:
            token = pipe.settings.admin_token
            if token:
                return self.headers.get("X-Admin-Token", "") == token
            return self._client() in ("127.0.0.1", "::1")

        def _auto_approve(self) -> bool:
            """KB_APPROVAL=off 全放行；on 全审批；auto 仅本机管理员直通。"""
            mode = (pipe.settings.kb_approval or "auto").strip().lower()
            if mode == "off":
                return True
            if mode == "on":
                return False
            return self._is_admin()


        def _presented_key(self) -> str:
            auth = (self.headers.get("Authorization") or "").strip()
            if auth.lower().startswith("bearer "):
                return auth[7:].strip()
            return (self.headers.get("X-API-Key") or "").strip()

        def _api_auth(self) -> tuple[str | None, str | None]:
            """未配置 API_KEYS 时保持开放；配置后必须带有效 Key。"""
            if not api_keys.enabled:
                return None, None
            return api_keys.identify(self._presented_key())

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
                metrics.inc("rag_api_tokens_total", {"key": pre["api_key"]}, tokens)
                if cost_usd:
                    metrics.inc("rag_api_cost_usd_total", {"key": pre["api_key"]}, value=cost_usd)
            if result.get("degraded"):
                metrics.inc("rag_retrieval_degraded_total",
                            {"reason": str(result.get("degrade_reason") or "unknown")})

            guards.audit.write(
                "ask", client=pre["client"], query=pre["query"][:200],
                trace_id=result.get("trace_id"), request_id=pre["request_id"],
                behavior=behavior, mode=mode, session_id=pre["session_id"],
                retrieval_score=result.get("retrieval_score"), model=result.get("model"),
                canary=bool(pre["model"]), budget_blocked=pre["budget_blocked"], tokens=tokens,
                llm_tokens=llm_tokens, embedding_tokens=embed_tokens, cost_usd=cost_usd,
                latency_ms=result.get("latency_ms"), path=answer_path,
                api_called=bool(result.get("api_called")),
                keyword_terms=result.get("keyword_terms"),
                keyword_gate=result.get("keyword_gate"),
                keyword_rejected=[f"{r.get('term')}:{r.get('reason')}"
                                  for r in (result.get("keyword_rejected") or [])],
                stream=path_label.endswith("/stream"),
                api_key=pre.get("api_key"),
            )

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path in ("/", "/index.html"):
                self._send(200, HOME_HTML, "text/html; charset=utf-8")
            elif path == "/ask":
                self._send(200, ASK_HTML, "text/html; charset=utf-8")
            elif path == "/kb":
                self._send(200, KB_HTML, "text/html; charset=utf-8")
            elif path == "/insights":
                kb_status = store.status() if store is not None else None
                self._send(200, render_insights(collect_report(pipe), kb_status),
                           "text/html; charset=utf-8")
            elif path in ("/dashboard", "/report"):
                target = "/insights#p-report" if path == "/report" else "/insights#p-overview"
                self._redirect(target)
            elif path == "/api/report/export":
                html = render_report(collect_report(pipe), standalone=True).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="report.html"')
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
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
                })
            elif path == "/metrics":
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

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
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

                if pre["cached"] is not None:
                    metrics.inc("rag_idempotent_replay_total")
                    guards.audit.write("ask.idempotent_replay", client=pre["client"],
                                       key=pre["idem_key"],
                                       trace_id=pre["cached"].get("trace_id"),
                                       request_id=pre["request_id"])
                    send("final", pre["cached"])
                    return

                started = time.time()
                try:
                    for event, data in pipe.ask_stream(
                            pre["query"], model=pre["model"],
                            force_extractive=pre["budget_blocked"],
                            session_id=pre["session_id"]):
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
                except Exception as exc:  # noqa: BLE001 —— 已经开始写 SSE，只能发错误事件
                    try:
                        send("error", {"error": str(exc)[:300]})
                    except Exception:  # noqa: BLE001
                        pass
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
        do_HEAD = do_GET

        def log_message(self, fmt: str, *args) -> None:
            pass

    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd, pipe


def main() -> None:
    ap = argparse.ArgumentParser(description="文档问答助手 Web 服务")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--model", help="临时指定模型（等价于设置 LLM_MODEL）")
    args = ap.parse_args()

    if args.model:
        os.environ["LLM_MODEL"] = args.model

    httpd, pipe = create_server(args.host, args.port)
    print(f"serving http://{args.host}:{args.port}  model={pipe.settings.model} base={pipe.settings.api_base}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
