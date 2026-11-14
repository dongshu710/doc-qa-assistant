"""只读接口：页面 + 查询类 API。

为什么单独一层：读接口全部无副作用，和写接口混在一起最容易把「顺手写点东西」带进来。
"""
from __future__ import annotations

import json
import os
import select
import time
from collections import Counter
from datetime import datetime
from urllib.parse import parse_qs, quote, urlparse

from .. import (ingest,
                kbstore,
                openai_compat,
                report,
                routing,
                suggest)
from .. import update as update_mod
from ..metrics import summarize
from ..notes.tools import tools_payload as notes_tools_payload
from ..openapi import build_spec
from ..theme import FILES_PAGE
from ..version import __version__
from ..web_pages import ASK_HTML, DEBUG_HTML, KB_HTML
from .common import (ALLOWED_EXT, SSE_HEARTBEAT_S, SSE_MAX_SECONDS, _read_jsonl,
                     _safe_name)
from .base import sse_acquire, sse_release


def _int_qs(qs: dict, key: str, default: int, low: int, high: int) -> int:
    """URL 里的整数参数：坏值一律回落默认值，并夹在区间内。

    不直接 `int(...)`：`?limit=abc` 会抛 ValueError 穿过 do_GET，
    客户端只看得到连接重置——项目里最难查的一类故障（没有状态码、没有响应体）。
    """
    try:
        value = int((qs.get(key) or [""])[0])
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


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
        # protocol_version / timeout / COMPRESSIBLE 只在 base.py 定义一次。
        # 这四个类通过 MRO 组合成一个 Handler，重复定义时生效的永远是最左边那份，
        # 改另一份会静默不生效——比没有更糟。

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            if self._guard("GET", path):
                return

            if path == "/mcp":
                if "text/event-stream" in (self.headers.get("Accept") or "").lower():
                    self._mcp_stream()
                    return
                # 没要下行流就明确指路：405 比让客户端对着 404 猜要省时间
                self._json({"error": "method_not_allowed",
                            "message": "MCP 请求走 POST /mcp（JSON-RPC）；"
                                       "需要下行流时在 Accept 里带 text/event-stream"},
                           405, {"Allow": "POST", **(self._cors_headers() or {})})
                return

            if path == "/v1/models":
                # OpenAI 兼容：SDK 与 LiteLLM 启动时会先探这个端点，
                # 拿不到就认为 base_url 配错，后面的 chat 请求根本不会发。
                self._json(openai_compat.models_payload(
                    pipe.settings.model or "jiyi"), 200, self._cors_headers())
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
            # 剩下的都是页面与只读接口，搬进 _get_pages 便于定位；
            # 那条链末尾自带 404 兜底，这里不用再加。
            self._get_pages(path, qs)


        def _get_pages(self, path: str, qs: dict) -> None:
            """页面与只读接口的总入口：按资源转交，顺序与原 elif 链一致。"""
            if path.startswith("/api/admin/") or path in ("/api/audit", "/api/metrics"):
                self._get_admin(path, qs)
            elif path.startswith(("/api/kb/", "/api/cases", "/api/examples",
                                  "/api/knowledge", "/api/keywords")):
                self._get_kb_view(path, qs)
            elif path in ("/api/l3", "/openapi.json", "/api/health", "/metrics"):
                self._get_meta(path, qs)
            elif path.startswith("/api/"):
                self._get_api_misc(path, qs)
            else:
                self._get_page_html(path, qs)
            return

        def _get_page_html(self, path: str, qs: dict) -> None:
            """页面分派：清单在 `routing.PAGE_ROUTES`，这里只负责把键换成 HTML。"""
            if path in routing.PAGE_ALIASES:
                # 只留问答、知识库、笔记、汇报四页，旧入口统一回落到问答页
                self._redirect("/ask")
                return
            moved = routing.PAGE_MOVED.get(path)
            if moved:
                # 301 而不是 302：改名是永久的，浏览器与搜索引擎都该记住新地址
                self._redirect(moved, 301)
                return
            page = routing.PAGE_ROUTES.get(path)
            if page is None:
                self._not_found(self.command, path)
                return
            if page == "report":
                # 汇报页的数据每次都可能变（trace、知识库、配置），不能像静态页那样预拼
                self._report_page(qs)
                return
            html = {"ask": ASK_HTML, "files": FILES_PAGE, "kb": KB_HTML,
                    "debug": DEBUG_HTML}[page]
            self._send(200, html, "text/html; charset=utf-8")

        def _report_page(self, qs: dict) -> None:
            """汇报页：展示 + 管理台入口；`?download=1` 返回可离线打开的独立副本。

            复用同一路径而不是新开 `/api/report/export`：少一个端点就少一份契约要维护，
            而且下载下来的文件和页面上看到的确实是同一套渲染。
            """
            # 只认 1/true/yes。`?download=0` 也返回附件的话，页面会进入离线态、按钮全灰。
            flag = (qs.get("download") or [""])[0].lower()
            as_file = flag in ("1", "true", "yes")
            # 页面在鉴权表里是 open（汇报页的用途就是能发给别人看），但它渲染了
            # 文档清单与模型端点。配了 API_KEYS 又没带 Key 时降级成「公开视图」：
            # 删清单、隐端点，而不是整页 403——参考 AnythingLLM 的做法，
            # 按角色裁剪内容，而不是把人挡在门外。
            _name, err = self._api_auth()
            redacted = bool(err)
            try:
                data = report.collect(pipe)
                if redacted:
                    data = report.redact(data)
                # 管理入口默认不渲染：汇报页的读者是业务方，不该看见「删除文档」
                # 与灰度配置。需要时加 ?admin=1（可收藏），脱敏视图永远不给。
                want_admin = (qs.get("admin") or [""])[0].lower() in ("1", "true", "yes")
                html = report.render(data, standalone=as_file, redacted=redacted,
                                     admin=want_admin and not redacted and not as_file)
            except Exception as exc:   # 未捕获异常会让客户端只看到连接重置
                self._json({"ok": False, "error": "report_failed",
                            "message": self._error_text(exc, "汇报页渲染失败")}, 500)
                return
            extra = ({"Content-Disposition": 'attachment; filename="report.html"'}
                     if as_file else None)
            self._send(200, html, "text/html; charset=utf-8", extra)

        def _get_meta(self, path: str, qs: dict) -> None:
            """发布与运行时自述：L3 报表、OpenAPI、健康检查、Prometheus。"""
            if path == "/api/l3":
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
                    # 目录监听状态：改了文件没生效时，这里能看出监听是否在跑
                    "kb_watch": self._watch_status(),
                    # 观测导出：没配时回 enabled=false；配错时把原因带出来
                    "otel": self._otel_status(),
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
            else:
                self._not_found(self.command, path)

        def _watch_status(self) -> dict:
            """监听线程的状态。关闭时也回 enabled=false，而不是省略这个键——
            省略会让「没开」和「旧版本没有这个功能」看起来一样。"""
            watcher = getattr(self.server, "kb_watcher", None)
            if watcher is None:
                return {"enabled": False}
            return {"enabled": True, "interval_s": watcher.interval,
                    "reloads": watcher.reloads, "last_error": watcher.last_error}

        def _otel_status(self) -> dict:
            tracer = getattr(self.server, "tracer", None)
            if tracer is None:
                error = getattr(self.server, "tracer_error", "")
                return {"enabled": False, "error": error}
            return tracer.stats()

        def _get_admin(self, path: str, qs: dict) -> None:
            """管理面：灰度配置、成本、审计、内部指标，级别在 routing 表里是 ADMIN。"""
            if path == "/api/admin/config":
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
            else:
                self._not_found(self.command, path)

        def _get_kb_doc_read(self, path: str, qs: dict) -> bool:
            """单文档读侧：原件与分段。

            为什么不并进 `_get_kb_view`：那边是「版本 / 审批 / 文档清单」，
            回答的是「库里有什么」；这里读的是**当前索引内存**与 raw 目录，
            回答的是「这份文档长什么样」。两类问题的生命周期都不一样
            （索引换代 vs 版本发布），混在一条 200 行的链上只会两边都难改。
            返回 True 表示已经写过响应，调用方直接 return。
            """
            if path == "/api/knowledge/raw":
                # 上传时的原件（PDF / DOCX / XLSX …）。用途只有一个：引用里带页码时
                # 能「打开第 N 页」对回原件——解析后的 md 已经丢掉了版式。
                name = _safe_name((qs.get("name") or [""])[0], ingest.SUPPORTED_EXT, 120)
                if not name:
                    self._json({"error": "name 只能是文件名"}, 400)
                    return True
                # 双保险：文件名已经过滤过路径分隔符，这里再按 realpath 确认没跑出 RAW_DIR
                root = os.path.realpath(raw_dir)
                full = os.path.realpath(os.path.join(root, name))
                if os.path.commonpath([full, root]) != root or not os.path.isfile(full):
                    self._json({"error": "原件不存在（只有文档类上传会留存原件）"}, 404)
                    return True
                with open(full, "rb") as f:
                    blob = f.read()
                # HTML / EML 一律当附件下载：内联渲染等于把上传者写的脚本放到本服务源上跑，
                # 它能直接调 /api/*（单机也一样）。PDF 才允许 inline，浏览器 PDF 阅读器不执行脚本。
                ext = os.path.splitext(name)[1].lower()
                inline = {".pdf": "application/pdf"}
                ctype = inline.get(ext, "application/octet-stream")
                disp = "inline" if ext in inline else "attachment"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Content-Disposition",
                                 f"{disp}; filename*=UTF-8''{quote(name)}")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cache-Control", "private, max-age=600")
                self.end_headers()
                self.wfile.write(blob)
                return True
            if path == "/api/knowledge/chunks":
                # 单文档分段速览：知识库行内「分段」抽屉、以及「用本文档测一次」的前置信息。
                # 不挂在 /api/kb 下，是因为这里读的是索引内存，与版本库的文档历史是两件事。
                raw = (qs.get("name") or [""])[0]
                # 知识库目录里只会是解析后的 .md（以及手传的 .txt），所以用 ALLOWED_EXT
                name = _safe_name(raw, ALLOWED_EXT, 120)
                if not name:
                    self._json({"error": "name 只能是文件名"}, 400)
                    return True
                detail = pipe.doc_chunks(name.rsplit(".", 1)[0])
                if detail is None:
                    self._json({"error": "文档不存在或尚未建立索引", "name": name,
                                "rebuilding": bool(pipe.rebuild_state().get("rebuilding"))}, 404)
                    return True
                self._json(detail)
                return True
            return False

        def _get_kb_view(self, path: str, qs: dict) -> None:
            """知识库读侧：用例、示例、版本清单、变更、文档历史、关键词。"""
            if self._get_kb_doc_read(path, qs):
                return
            if path == "/api/cases":
                curated = _read_jsonl(os.path.join(project_root, "tests", "eval_cases.jsonl"), 100000)
                fb_cases = _read_jsonl(feedback_cases_path, 100000)
                doc_cases = _read_jsonl(doc_cases_path, 100000)
                last_run = None
                try:
                    if os.path.exists(run_report_path):
                        with open(run_report_path, encoding="utf-8") as f:
                            rep = json.load(f)
                        last_run = {k: rep.get(k) for k in
                                    ("run_at", "scope", "total", "passed", "pass_rate", "channel", "model")}
                except (OSError, ValueError, TypeError):
                    # 上次运行被中断会留下截断的 JSON。这里不能让它冒泡：
                    # 一次异常会让 /api/cases 永久 500，管理面板的「评测」组整块打不开。
                    last_run = None
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
                # 每份文档有哪些页：状态列要能区分「PDF 有页码」与「PDF 转出来没页标」，
                # 后者在调页码引用时是硬伤（无法跳到第 N 页），但不影响检索，所以只是提示。
                pages_of: dict[str, set] = {}
                for c in pipe.chunks:
                    page_no = getattr(c, "page", None)
                    if page_no:
                        pages_of.setdefault(c.doc_id, set()).add(page_no)
                files = []
                # 清单来源统一走 kbstore 的 manifest。原来这里是自己 listdir，
                # 与 /api/health、汇报页各算一遍：审批通过到索引重建完成之间，
                # kb_dir() 与 pipe.knowledge_dir 必然不同，三个接口会给出不同的文件集。
                names: list[str] = []
                if store is not None:
                    try:
                        names = store.doc_names()
                    except (kbstore.KnowledgeError, OSError):
                        names = []
                if not names and os.path.isdir(kb_dir()):
                    # manifest 缺失或知识库未初始化：退回目录扫描，页面至少还能显示
                    names = sorted(n for n in os.listdir(kb_dir())
                                   if n.lower().endswith(ALLOWED_EXT))
                for name in names:
                    try:
                        full = os.path.join(kb_dir(), name)
                        doc_id = name.rsplit(".", 1)[0]
                        pages = pages_of.get(doc_id) or set()
                        # 状态只从索引事实推导，不读解析日志：解析警告从来没落过盘，
                        # 编一个「degraded」字段出来只会让人以为能查到。
                        if not counts.get(doc_id):
                            status = "no_index"
                        elif name.lower().endswith((".pdf", ".pptx")) and not pages:
                            status = "no_page"
                        else:
                            status = "ok"
                        files.append({
                            "name": name,
                            "chunks": counts.get(doc_id, 0),
                            "size": os.path.getsize(full),
                            "mtime": datetime.fromtimestamp(os.path.getmtime(full)).strftime("%Y-%m-%d %H:%M"),
                            "status": status,
                            "pages": len(pages),
                        })
                    except OSError:
                        # 并发删除/改名：跳过这一条。少显示一份，比整个列表 500 好。
                        continue
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
                name = _safe_name((qs.get("name") or [""])[0])
                if name:
                    doc_id = name.rsplit(".", 1)[0]
                    if doc_id not in pipe.keywords.docs:
                        self._json({"error": "文档不存在或未生成关键词"}, 404)
                        return
                    self._json(pipe.keywords.doc_view(doc_id))
                    return
                # 一次算完每个文档的条目数。原写法是嵌套推导式（文档数 × 全部条目），
                # 500 文档 / 25k 条时实测 338ms，文档翻倍就是 4 倍。
                per_doc = Counter(e.doc_id for e in pipe.keywords.entries)
                self._json({
                    "summary": pipe.keywords.summary(),
                    "docs": [
                        {"doc_id": doc_id, "title": meta.get("title") or doc_id,
                         "count": per_doc.get(doc_id, 0),
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
            else:
                self._not_found(self.command, path)

        def _get_api_misc(self, path: str, qs: dict) -> None:
            """剩下的只读接口：原文、反馈列表、调用轨迹，末尾是 404 兜底。"""
            if path == "/api/source":
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
                limit = _int_qs(qs, "limit", 20, 1, 200)
                self._json({"items": list(reversed(_read_jsonl(feedback_path, limit)))})
            elif path == "/api/trace":
                limit = _int_qs(qs, "limit", 20, 1, 200)
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
                self._not_found(self.command, path)


        def _mcp_stream(self) -> None:
            """GET /mcp：Streamable HTTP 的下行流。

            本服务没有「服务端主动发起的请求」，所以这条流不做业务推送，
            只做两件事：让严格按规范先 GET 的客户端拿到 200，以及用注释帧保活。
            **不伪造任何 JSON-RPC 消息**——凭空发出的通知会污染客户端状态，
            比不实现更糟。

            有硬上限（SSE_MAX_SECONDS）和并发名额：长连接占的是请求线程，
            没上限的话几条挂死的流就能把整个服务拖到不响应。
            """
            if not sse_acquire():
                self._json({"error": "too_many_streams",
                            "message": "SSE 连接数已达上限，请稍后重试"},
                           429, self._cors_headers())
                return
            try:
                if not self._sse_open():
                    return
                deadline = time.monotonic() + SSE_MAX_SECONDS
                while time.monotonic() < deadline:
                    # 用 select 等一个心跳周期：对端一关，socket 立刻可读，
                    # 能马上释放名额；只 sleep 的话，客户端断开后还要白占
                    # 一整个周期，连续开关几次就把并发名额耗光了。
                    try:
                        ready, _, _ = select.select([self.connection], [], [], SSE_HEARTBEAT_S)
                    except (OSError, ValueError):
                        return
                    if ready:
                        try:
                            if not self.connection.recv(1):
                                return      # 收到 EOF：客户端已经走了
                        except OSError:
                            return
                    if not self._sse_raw(": ping\n\n"):
                        return
            finally:
                sse_release()

    return ReadRoutes
