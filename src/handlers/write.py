"""写接口：问答 / 知识库 / 设置 / 评测用例。

为什么单独一层：写接口最多、也最需要逐个检查鉴权与体积上限；单独成文件便于审阅。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import queue
import shutil
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from .. import (casegen, dify, evaluator, ingest, jsonl, kbstore, openai_compat as compat)
from .common import (ALLOWED_EXT, ASK_MAX_BYTES, ASSET_BODY_MAX, DOC_B64_MAX_BYTES,
                     DOC_MAX_BYTES,
                     MAX_BODY_BYTES, SSE_HEARTBEAT_S, SSE_MAX_SECONDS,
                     UPLOAD_MAX_BYTES,
                     _read_jsonl,
                     _safe_name)
# 流式回答同样是长连接，必须和 /mcp 共用同一套名额。
# 之前这里没接，`_SSE_LIMIT` 只护住了 MCP，问答流是完全不受限的。
from .base import sse_acquire, sse_limit, sse_release


def behavior_of(result: dict) -> str:
    """把行为收敛成一个低基数标签——span 属性做维度，不能带自由文本。"""
    return str((result or {}).get("behavior") or "unknown")[:24]


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
    _mcp_targets = deps._mcp_targets
    _picker_command = deps._picker_command
    _pick_folder = deps._pick_folder
    _count_notes = deps._count_notes
    _copy_notes = deps._copy_notes
    tracer = deps.tracer

    class WriteRoutes:
        # protocol_version / timeout / COMPRESSIBLE 只在 base.py 定义一次。
        # 这四个类通过 MRO 组合成一个 Handler，重复定义时生效的永远是最左边那份，
        # 改另一份会静默不生效——比没有更糟。

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if self._guard("POST", path):
                return
            if path == "/v1/chat/completions":
                # OpenAI 兼容面：给 SDK / LiteLLM / LangChain 用。
                # 放在最前面是因为它不在 `/api/` 下，下面那张白名单与体积表
                # 都是按 /api 组织的，混进去会把两套语义搅在一起。
                self._post_openai()
                return
            if path == "/mcp":
                # MCP over HTTP：JSON-RPC 直接 POST，复用同一份 tools 与 NoteService
                body, err = self._read_note_body(allow_list=True)
                if err:
                    self._json({"jsonrpc": "2.0", "id": None,
                                "error": {"code": -32700, "message": err}}, 400)
                    return
                self._mcp_http(body)
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
                # 上传附件走 base64，请求体会比普通笔记大一个数量级；
                # 只有这条路径放宽，其它笔记接口仍按 2 MB 卡。
                wide = "/assets" in path
                body, err = self._read_note_body(max_bytes=ASSET_BODY_MAX if wide else None)
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
                            "/api/kb/seed",
                            "/api/keywords/rebuild", "/api/session/clear",
                            "/api/search/debug",
                            "/api/admin/config", "/api/admin/rollback",
                            "/dify/retrieval"):
                self._not_found(self.command, path)
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
            elif path in ("/api/ask", "/api/ask/stream"):
                limit = ASK_MAX_BYTES
            else:
                limit = MAX_BODY_BYTES
            if length <= 0:
                self._json({"ok": False, "error": "invalid_argument",
                            "message": "请求体为空"}, 400)
                return
            if length > limit:
                self._json({"ok": False, "error": "payload_too_large",
                            "message": f"请求体 {length} 字节，超过该接口上限 {limit // 1024} KB"},
                           413)
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._json({"ok": False, "error": "invalid_json",
                            "message": "请求体不是合法 JSON"}, 400)
                return

            # 按资源转交。原来是 641 行的 if 链，改任何一处都要在这条链上找位置，
            # 且分支顺序隐含语义（谁先匹配）。现在只留这一层分派，
            # 每组内部的顺序与条件原样保留。
            if path.startswith("/api/admin/"):
                self._post_admin(path, payload)
            elif path.startswith(("/api/knowledge/", "/api/kb/")):
                self._post_kb(path, payload)
            elif (path.startswith(("/api/cases/", "/api/keywords/", "/api/session/"))
                  or path in ("/api/feedback", "/api/reload", "/api/search/debug")):
                self._post_data(path, payload)
            elif path == "/dify/retrieval":
                # Dify 会把配置的端点名后面拼上 /retrieval，所以这里就这一个路径。
                # 它不在 /api/ 下：那是本项目的接口面，这是给外部平台用的适配面。
                self._post_dify(payload)
            else:
                self._post_ask(path, payload)
            return

        def _post_dify(self, payload: dict) -> None:
            """Dify 外部知识库：检索 → records。生成交给 Dify，这里绝不碰模型。

            错误按 Dify 约定的 `{error_code, error_msg}` 返回。它只看 HTTP 状态码，
            非 200 一律变成界面上一句「外部知识库调用失败」——真正的原因不写进 body
            就等于没写，排障的人只能去翻服务端日志。
            """
            try:
                query, top_k, threshold = dify.parse_request(payload)
            except dify.DifyError as exc:
                self._json({"records": [], "error_code": exc.code,
                            "error_msg": str(exc)}, 400)
                return
            try:
                items = dify.records(pipe, query, top_k, threshold)
            except Exception as exc:  # noqa: BLE001 —— 索引损坏等：如实报错，不假装空结果
                self._json({"records": [], "error_code": 5000,
                            "error_msg": self._error_text(exc, "检索失败")}, 500)
                return
            metrics.inc("rag_dify_retrieval_total")
            # 没有命中就回空数组。Dify 的约定是「检索不到不算错」，它会把这条知识库
            # 当没有贡献继续走；这里回 404/500 反而会让整个应用报错。
            self._json({"records": items})

        def _compat_error(self, exc: "compat.CompatError",
                          extra_headers: dict | None = None) -> None:
            """OpenAI 形状的错误体。SDK 只读 `error.message`，回主协议会让它失明。"""
            metrics.inc("rag_openai_error_total", {"code": exc.code})
            self._json(exc.body(), exc.status, extra_headers=extra_headers)

        def _post_openai(self) -> None:
            """OpenAI 兼容的 chat.completions：非流式与流式两条路。

            复用 `_ask_preflight`：鉴权、限流、幂等、灰度、预算五件事一套口径。
            另起一套的话，同一个 Key 在 `/api/ask` 与 `/v1` 上会有两种限额，
            用户看到的是「有时 429 有时不限」。
            """
            body, err = self._read_note_body(max_bytes=ASK_MAX_BYTES)
            if err:
                self._compat_error(compat.CompatError(err))
                return
            model = str(body.get("model") or pipe.settings.model or "jiyi")
            try:
                for name in compat.UNSUPPORTED:
                    if body.get(name):
                        raise compat.CompatError(
                            f"不支持 {name}：本服务只依据资料作答，不做工具调用",
                            code="unsupported_parameter")
                try:
                    if int(body.get("n") or 1) != 1:
                        raise compat.CompatError("只支持 n=1（一次检索只有一份证据）",
                                                 code="unsupported_parameter")
                except (TypeError, ValueError):
                    raise compat.CompatError("n 必须是整数", code="invalid_parameter")
                query, ignored = compat.messages_to_query(body.get("messages"))
            except compat.CompatError as exc:
                self._compat_error(exc)
                return

            pre, fail = self._ask_preflight({"query": query,
                                             "session_id": body.get("session_id")})
            if fail:
                payload, code, headers = fail
                kind = {401: "authentication_error", 429: "rate_limit_error"}.get(
                    int(code), "invalid_request_error")
                self._compat_error(compat.CompatError(
                    str(payload.get("message") or "请求被拒绝"), status=int(code),
                    kind=kind, code=str(payload.get("error") or "request_rejected")),
                    headers)
                return

            if body.get("stream"):
                # 长连接名额与 /api/ask/stream、/mcp 共用一套，断开必须还回去。
                if not sse_acquire():
                    self._compat_error(compat.CompatError(
                        f"同时进行的流式回答已达上限（{sse_limit()} 条）", status=429,
                        kind="rate_limit_error", code="too_many_streams"),
                        {"Retry-After": "2"})
                    return
                cancel = threading.Event()
                try:
                    self._openai_stream(pre, model, cancel, ignored)
                finally:
                    cancel.set()
                    sse_release()
                return

            started = time.monotonic()
            result = pipe.ask(pre["query"], model=pre["model"],
                              force_extractive=pre["budget_blocked"],
                              session_id=pre["session_id"])
            self._annotate_result(result, pre)
            self._record_ask(result, pre, started, "/v1/chat/completions")
            payload = compat.to_chat_completion(result, model, pre["request_id"])
            if ignored:
                payload["x_ignored_parts"] = ignored
            self._json(payload, extra_headers={
                "X-Request-Id": pre["request_id"],
                "X-Answer-Path": str(result.get("path") or "rag"),
            })

        def _openai_stream(self, pre: dict, model: str,
                           cancel: threading.Event, ignored: int = 0) -> None:
            """把内部事件流翻译成 `chat.completion.chunk`。

            与 `/api/ask/stream` 的差别只有协议格式：内部是 `delta/replace/final`
            三种语义，OpenAI 只有「追加」。`replace` 用 `suffix_for` 折算成追加，
            折算不掉的极端情况（生成被整段改写）会在结尾用 final 再补一次差量。
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

            completion = compat.completion_id()
            created = int(time.time())
            sent = ""

            def emit(frame: str) -> bool:
                try:
                    self.wfile.write(frame.encode("utf-8"))
                    self.wfile.flush()
                    return True
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    # 客户端走了：立刻取消生成，别让这一轮 token 白烧。
                    self.close_connection = True
                    cancel.set()
                    return False

            if not emit(compat.to_sse_chunk("", model, completion, created, role=True)):
                return

            started = time.monotonic()
            events: queue.Queue = queue.Queue()

            def produce() -> None:
                stream = None
                try:
                    stream = pipe.ask_stream(pre["query"], model=pre["model"],
                                             force_extractive=pre["budget_blocked"],
                                             session_id=pre["session_id"])
                    for item in stream:
                        if cancel.is_set():
                            break
                        events.put(item)
                except Exception as exc:  # noqa: BLE001 —— 生成线程的异常要回传给请求线程
                    events.put(("__error__", str(exc)[:300]))
                finally:
                    if stream is not None:
                        closer = getattr(stream, "close", None)
                        if closer is not None:
                            try:
                                closer()
                            except Exception:  # noqa: BLE001
                                pass
                    events.put(("__done__", None))

            threading.Thread(target=produce, name="openai-stream", daemon=True).start()
            final: dict | None = None
            try:
                while True:
                    if time.monotonic() - started > SSE_MAX_SECONDS:
                        emit(compat.error_frame(f"回答超过 {int(SSE_MAX_SECONDS)} 秒，已中断",
                                                "timeout_error", "timeout"))
                        break
                    try:
                        event, data = events.get(timeout=SSE_HEARTBEAT_S)
                    except queue.Empty:
                        # OpenAI 客户端不解析 SSE 注释，发心跳只会变成噪音；
                        # 300 秒硬上限已经保证连接不会无限挂着。
                        continue
                    if event == "__done__":
                        break
                    if event == "__error__":
                        emit(compat.error_frame(str(data)))
                        break
                    if event in ("delta", "replace"):
                        piece = compat.suffix_for(sent, str(data or ""))
                        if piece:
                            sent += piece
                            if not emit(compat.to_sse_chunk(piece, model, completion, created)):
                                return
                    elif event == "final":
                        final = data
                        piece = compat.suffix_for(sent, str(data.get("answer") or ""))
                        if piece:
                            sent += piece
                            if not emit(compat.to_sse_chunk(piece, model, completion, created)):
                                return
            except (BrokenPipeError, ConnectionResetError):
                cancel.set()
                return

            if final is not None:
                self._annotate_result(final, pre)
                self._record_ask(final, pre, started, "/v1/chat/completions")
            usage = compat.usage_of(final or {})
            emit(compat.to_sse_chunk("", model, completion, created, finish="stop",
                                     usage=usage))
            emit(compat.sse_done())

        def _post_admin(self, path: str, payload: dict) -> None:
            """管理员动作：灰度比例与运行时回滚。两条都先过管理员校验。"""
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
            # 分派层只把本组的路径交进来；真有不认识的也从这里回 404，
            # 不能让请求挂在一个没有 response 的方法里。
            self._not_found(self.command, path)

        def _post_kb(self, path: str, payload: dict) -> None:
            """按路径再分一层，具体处理见下面的方法。"""
            if path in ("/api/knowledge/upload_pdf", "/api/knowledge/upload_file"):
                self._post_kb_doc(path, payload)
            elif path == "/api/knowledge/upload":
                self._post_kb_upload(path, payload)
            elif path == "/api/kb/seed":
                self._post_kb_seed(payload)
            else:
                self._post_kb_review(path, payload)
            return

        def _post_kb_seed(self, payload: dict) -> None:
            """空库引导：把仓库自带的演示文档一键导入。

            为什么不直接内嵌示例文本：示例必须和 `data/knowledge/` 里那份**是同一份**，
            否则演示文档改了、种子数据没跟着改，用户装完看到的是一套过期内容。
            所以这里只做「读仓库里的文件 → 走正常入库链路」。

            不造「客服问答对」这一类模板：仓库里没有对应的示范文档，
            凭空写一份假的问答对进去，只会让人以为系统自带的语料就长这样。
            """
            templates = {
                "policy": {
                    "title": "制度办法",
                    "names": ["02_客户适当性管理制度.md",
                              "pdf_演示制度_信息披露与消费者权益保护办法.md",
                              "pdf_演示制度_销售适当性管理实施细则.md"],
                },
                "product": {
                    "title": "产品要素",
                    "names": ["01_理财产品要素说明.md", "03_大额存单与定期存款.md"],
                },
                "regulatory": {
                    "title": "监管摘录",
                    "names": ["pdf_监管摘录_商业银行理财业务监督管理办法.md"],
                },
            }
            key = str(payload.get("template") or "").strip()
            chosen = templates.get(key)
            if chosen is None:
                self._json({"ok": False, "error": "invalid_argument",
                            "message": "template 只能是 " + " / ".join(templates)}, 400)
                return
            source_dir = os.path.join(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))), "data", "knowledge")
            if not os.path.isdir(source_dir):
                self._json({"ok": False, "error": "seed_missing",
                            "message": "找不到内置演示文档（data/knowledge），"
                                       "请直接把文件拖进上传框"}, 404)
                return
            files: dict[str, str] = {}
            skipped: list[str] = []
            existing = set()
            if os.path.isdir(kb_dir()):
                existing = {n for n in os.listdir(kb_dir()) if n.lower().endswith(ALLOWED_EXT)}
            for name in chosen["names"]:
                safe = _safe_name(name, ALLOWED_EXT, 120)
                if not safe:
                    continue
                if safe in existing:
                    # 幂等：重复点不会生成同名覆盖的那条「旧内容没了」告警
                    skipped.append(safe)
                    continue
                try:
                    with open(os.path.join(source_dir, safe), encoding="utf-8") as f:
                        files[safe] = f.read()
                except OSError:
                    continue
            if not files:
                self._json({"ok": True, "template": key, "added": [], "skipped": skipped,
                            "message": "这些文档已经在知识库里了"})
                return
            if store is not None:
                try:
                    _staged, change_id, approved, total = self._stage_and_maybe_approve(
                        files, note=f"空库模板：{chosen['title']}")
                except (kbstore.KnowledgeError, ValueError) as exc:
                    self._json({"ok": False, "error": str(exc)}, 400)
                    return
                except Exception as exc:  # noqa: BLE001
                    self._json({"ok": False, "error": f"入库失败：{exc}"}, 500)
                    return
                self._json({
                    "ok": True, "template": key, "title": chosen["title"],
                    "added": sorted(files), "skipped": skipped,
                    "pending": approved is None, "change_id": change_id,
                    "version": store.active_version(),
                    **index_fields(),
                })
                guards.audit.write("kb.seed", client=self._client(), template=key,
                                   files=len(files), pending=approved is None)
                return
            # 无版本库（KB_STORE=off）：直接落盘后重建
            for name, content in files.items():
                with open(os.path.join(kb_dir(), name), "w", encoding="utf-8") as f:
                    f.write(content)
            try:
                total = pipe.reload()
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"已写入但重载失败：{exc}"}, 500)
                return
            self._json({"ok": True, "template": key, "title": chosen["title"],
                        "added": sorted(files), "skipped": skipped, "chunks": total})
            guards.audit.write("kb.seed", client=self._client(), template=key,
                               files=len(files), chunks=total)

        def _post_kb_upload(self, path: str, payload: dict) -> None:
            """单份文本入库：走版本库暂存，按 KB_APPROVAL 决定是否直接生效。"""
            if path == "/api/knowledge/upload":
                name = _safe_name(payload.get("name"))
                content = str(payload.get("content") or "")
                if not name:
                    self._json({"ok": False, "error": "只支持 .md / .txt，文件名不合法"}, 400)
                    return
                if not content.strip():
                    self._json({"ok": False, "error": "文件内容为空"}, 400)
                    return

                if store is not None:
                    try:
                        staged, change_id, approved, total = self._stage_and_maybe_approve(
                            {name: content}, note=str(payload.get("note") or "")[:200])
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
                        # 同名覆盖必须让上传的人看见：写入是真的，旧内容也是真的没了
                        # （只在历史版本里）。原来 warnings 只存在 changes 接口里，
                        # 上传的回复干干净净，用户对「我覆盖了什么」一无所知。
                        "warnings": staged["change"].get("warnings") or [],
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
            # 组内条件互斥，走到这里说明分派给了不该给的路径。
            self._not_found(self.command, path)

        def _post_kb_doc(self, path: str, payload: dict) -> None:
            """文档上传：解码、解析、暂存，与文本走同一条审批链。

            支持 PDF / DOCX / PPTX / XLSX / CSV / TSV / HTML / EML，全部由
            `ingest` 按扩展名分派；解析结果统一成 Markdown 才进知识库，
            所以下游（切分、检索、引用、审批）完全不需要知道原始格式。
            """
            if path in ("/api/knowledge/upload_pdf", "/api/knowledge/upload_file"):
                name = _safe_name(payload.get("name"), ingest.SUPPORTED_EXT, 120)
                if not name:
                    self._json({"ok": False,
                                "error": "只接受纯文件名的 " + " / ".join(
                                    e.lstrip(".").upper() for e in ingest.SUPPORTED_EXT) + " 文件"}, 400)
                    return
                blob = payload.get("data_b64") or payload.get("file") or ""
                if not isinstance(blob, str) or not blob.strip():
                    self._json({"ok": False, "error": "文件内容为空"}, 400)
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
                # csv/tsv/html/eml 是纯文本，没有魔数可校验；
                # docx/pptx/xlsx 都是 ZIP（PK\x03\x04），PDF 有自己的头。
                magic = {".pdf": b"%PDF", ".docx": b"PK", ".pptx": b"PK",
                         ".xlsx": b"PK"}.get(ext, b"")
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
                        staged, change_id, approved, total = self._stage_and_maybe_approve(
                            {res["md"]: md_bytes},
                            note=f"由 {name} 解析（{res.get('engine')}）")
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
                    "slides": res.get("slides"),
                    "slides_empty": res.get("slides_empty"),
                    "attachments": res.get("attachments"),
                        # 新增格式的统计：PPT 页数、邮件附件数。不回传的话
                        # 用户看不到「这 3 页里 2 页是图」这种关键信息。
                        "slides": res.get("slides"),
                        "slides_empty": res.get("slides_empty"),
                        "attachments": res.get("attachments"),
                        "need_ocr": res.get("need_ocr"), "truncated": res.get("truncated"),
                        "pending": approved is None, "change_id": change_id,
                        "version": store.active_version(),
                        "warnings": staged["change"].get("warnings") or [],
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
            # 组内条件互斥，走到这里说明分派给了不该给的路径。
            self._not_found(self.command, path)

        def _post_kb_review(self, path: str, payload: dict) -> None:
            """删除与审批：approve 生成新版本，reject 留痕，rollback_doc 只退一份文档。"""
            if path == "/api/knowledge/delete":
                name = _safe_name(payload.get("name"))
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
                        staged, change_id, approved, total = self._stage_and_maybe_approve(
                            {}, deletes=[name], note=f"删除 {name}")
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
            # 组内条件互斥，走到这里说明分派给了不该给的路径。
            self._not_found(self.command, path)


        def _post_data(self, path: str, payload: dict) -> None:
            """按路径再分一层，具体处理见下面的方法。"""
            if path.startswith("/api/cases/"):
                self._post_cases(path, payload)
            else:
                self._post_ops(path, payload)
            return

        def _post_cases(self, path: str, payload: dict) -> None:
            """用例集：从文档/反馈生成，以及跑一遍评测。"""
            if path == "/api/cases/from_doc":
                name = _safe_name(payload.get("name"))
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
                started = time.monotonic()
                results, skipped = evaluator.run_cases(
                    pipe, cases, sleep=sleep_s, skip_missing_doc=True, kb_dir=kb_dir())
                summary = evaluator.summarize(results, skipped)
                report = {
                    "run_at": datetime.now(timezone.utc).isoformat(),
                    "scope": scope,
                    "channel": pipe.settings.channel,
                    "model": pipe.settings.model,
                    **summary,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "results": results,
                }
                # 非原子写 + 无保护的读是致命组合：进程在写一半时退出，
                # 会留下截断的 JSON，之后 /api/cases 每次都抛 JSONDecodeError，
                # 管理面板「评测」组永久打不开。复用版本库的原子写。
                kbstore._atomic_json(run_report_path, report)
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
            # 组内条件互斥，走到这里说明分派给了不该给的路径。
            self._not_found(self.command, path)

        def _post_ops(self, path: str, payload: dict) -> None:
            """运维动作：反馈落盘、关键词重建、清会话、索引热载、检索调试。"""
            if path == "/api/search/debug":
                # 只读动作，但用 POST：query 可能很长，放 query string 会被
                # 各种代理截断，中文还要再过一层编码，排障时最难查的就是这个。
                query = payload.get("query")
                if not isinstance(query, str) or not query.strip():
                    self._json({"ok": False, "error": "invalid_argument",
                                "message": "需要 query（要调试的检索问题）"}, 400)
                    return
                top_k = payload.get("top_k")
                if top_k is not None:
                    try:
                        top_k = int(top_k)
                    except (TypeError, ValueError):
                        self._json({"ok": False, "error": "invalid_argument",
                                    "message": "top_k 必须是整数"}, 400)
                        return
                # 只认文件名/文档 id 两种写法：带路径或控制字符一律 400，避免有人
                # 拿它当文件读取口（检索只按 doc_id 过滤，本来就不碰磁盘，但边界要守住）
                raw_doc = payload.get("doc")
                doc = ""
                if raw_doc not in (None, ""):
                    if not isinstance(raw_doc, str):
                        self._json({"ok": False, "error": "invalid_argument",
                                    "message": "doc 必须是字符串"}, 400)
                        return
                    candidate = raw_doc.strip()
                    if (not candidate or len(candidate) > 120 or "/" in candidate
                            or "\\" in candidate or ".." in candidate
                            or any(ch in candidate for ch in '<>:"|?*\x00')):
                        self._json({"ok": False, "error": "invalid_argument",
                                    "message": "doc 只能是文件名，不能带路径"}, 400)
                        return
                    # /kb 传文件名（带扩展名），引用卡片传 doc_id（不带）——两种都收
                    doc = candidate.rsplit(".", 1)[0] if "." in candidate else candidate
                try:
                    detail = pipe.debug_search(query.strip(), top_k=top_k, doc=doc or None)
                except Exception as exc:  # noqa: BLE001 —— 索引异常要如实报，不假装空结果
                    self._json({"ok": False, "error": "retrieval_error",
                                "message": self._error_text(exc, "检索失败")}, 500)
                    return
                detail["ok"] = True
                self._json(detail)
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
            # 组内条件互斥，走到这里说明分派给了不该给的路径。
            self._not_found(self.command, path)


        def _post_ask(self, path: str, payload: dict) -> None:
            """问答：流式与非流式共用 `_ask_preflight`，鉴权/限流/幂等一套口径。"""
            if path == "/api/ask/stream":
                pre, err = self._ask_preflight(payload)
                if err:
                    body, code, headers = err
                    self._json(body, code, extra_headers=headers)
                    return

                # 长连接名额与 /mcp 共用一套。之前这里没接，64 个线程全被慢流占满时
                # 全站不响应，而调用方拿到的只是「超时」——看起来像服务挂了。
                if not sse_acquire():
                    self._json({"ok": False, "error": "too_many_streams",
                                "message": f"同时进行的流式回答已达上限（{sse_limit()} 条），"
                                           "请改用非流式接口或稍后重试"},
                               429, extra_headers={"Retry-After": "2"})
                    return

                cancel = threading.Event()
                try:
                    self._stream_answer(pre, cancel)
                finally:
                    # 正常结束、超时、客户端断开，三条路都要把名额还回去。
                    # 漏还的后果是「出过一次异常之后永久 429」，比不限流更难查。
                    cancel.set()
                    sse_release()
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

            started = time.monotonic()
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
            return
            # 分派层只把本组的路径交进来；真有不认识的也从这里回 404，
            # 不能让请求挂在一个没有 response 的方法里。
            self._not_found(self.command, path)

        def _stream_answer(self, pre: dict, cancel: threading.Event) -> None:
            """把一次问答渲染成 SSE。

            `cancel` 由调用方在收尾时置位，也覆盖「客户端中途断开」。
            生成线程每出一块检查一次，取消就关掉生成器——不关的话，模型那一轮
            token 会照常跑完，只是没人收，成本却照记。
            """
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

            started = time.monotonic()
            events: queue.Queue = queue.Queue()

            # 生成放到独立线程：主线程要能在「模型还没吐第一个字」时发心跳，
            # 否则浏览器/代理会以为连接死了，而实际只是检索慢或模型排队。
            def produce() -> None:
                stream = None
                try:
                    stream = pipe.ask_stream(
                        pre["query"], model=pre["model"],
                        force_extractive=pre["budget_blocked"],
                        session_id=pre["session_id"])
                    for item in stream:
                        if cancel.is_set():
                            break
                        events.put(item)
                except Exception as exc:  # noqa: BLE001 —— 生成线程的异常要回传给请求线程
                    events.put(("__error__", str(exc)[:300]))
                finally:
                    # 取消时关掉生成器：close() 触发 GeneratorExit，上游的模型请求
                    # 立刻断开，而不是把整轮 token 跑完再丢掉。
                    if stream is not None:
                        closer = getattr(stream, "close", None)
                        if closer is not None:
                            try:
                                closer()
                            except Exception:  # noqa: BLE001
                                pass
                    events.put(("__done__", None))

            threading.Thread(target=produce, name="ask-stream", daemon=True).start()
            try:
                send_comment("connected")
                while True:
                    if time.monotonic() - started > SSE_MAX_SECONDS:
                        send("error", {"error": f"回答超过 {int(SSE_MAX_SECONDS)} 秒，已中断"})
                        cancel.set()
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
                # 客户端走了：立刻取消生成。用户拿不到答案，也就不该再为它烧 token
                # （产品口径：断开即取消，不按已生成部分计费）。
                cancel.set()

        # HEAD 复用 GET 的路由：_send 已经按 command 跳过响应体。
        # 不实现会返回 501，而 HTTP/1.1 的监控探针与部分代理默认先发 HEAD。
        def _ask_preflight(self, payload: dict):
            """问答前置：鉴权、限流、幂等、灰度与预算。JSON 与流式共用，避免两套口径。"""
            # 字段缺失与「给了空串」是两件事：
            #   空串 → 澄清（聊天场景里用户按了回车，回一句"请说明具体问题"是对的）；
            #   缺字段 → 400（调用方把 query 写成了 question，回澄清等于把
            #   参数名写错伪装成用户没输入，是最难自查的一类静默失败）。
            if not isinstance(payload, dict) or "query" not in payload:
                return None, ({"ok": False, "error": "invalid_argument",
                               "message": "缺少 query 字段；请求体应形如 {\"query\": \"你的问题\"}"},
                              400, {})
            if not isinstance(payload["query"], str):
                return None, ({"ok": False, "error": "invalid_argument",
                               "message": f"query 必须是字符串，收到 {type(payload['query']).__name__}"},
                              400, {})
            query = payload["query"]
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

            if tracer is not None:
                # 旁路：emit 只入队，永不抛、永不阻塞（队列满就丢并计数）。
                # 用 started 的单调钟换纳秒起点，保证 span 时长与 latency_ms 同一口径。
                elapsed_ns = int((time.monotonic() - started) * 1e9)
                tracer.emit("rag.ask", time.time_ns() - max(0, elapsed_ns), {
                    "rag.behavior": behavior_of(result),
                    "rag.path": str(result.get("path") or "rag"),
                    "rag.mode": str(result.get("mode") or ""),
                    "rag.latency_ms": int(result.get("latency_ms") or 0),
                    "rag.citations": len(result.get("citations") or []),
                    "rag.tokens": tokens,
                    "rag.api_called": bool(result.get("api_called")),
                    "http.route": path_label,
                })

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
                            result.get("latency_ms", 0) / 1000.0 or (time.monotonic() - started))
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
