"""HTTP 基类：响应、来源闸门、鉴权、通用动作。

为什么单独一层：这些方法每个路由都要用，混在路由文件里会被反复引用成环。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from .. import (routing, security)
from ..auth import safe_equal

# SSE 是长连接，一条流就占住一个请求线程。BoundedHTTPServer 总共 64 个线程，
# 几个挂死/半死的流就能把服务拖到不响应。所以单独限流：超过就回 429，
# 让后来的客户端立刻知道「现在满了」，而不是排队等到超时。
_SSE_LOCK = threading.Lock()
_SSE_ACTIVE = 0
_SSE_LIMIT = max(1, int(os.environ.get("MCP_SSE_MAX_CONN", "4") or 4))

# 这两个写接口的 Key 校验在 `_ask_preflight` 里做（还要记账、限流、算 session），
# 所以在 `_write_gate` 里放行。必须逐个列名：按前缀放过等于给未来所有
# `/api/ask*` 预开了后门。
ASK_PATHS_NO_KEY_GATE = frozenset({"/api/ask", "/api/ask/stream"})


def sse_acquire() -> bool:
    """占一个 SSE 名额；失败说明已达上限。"""
    global _SSE_ACTIVE
    with _SSE_LOCK:
        if _SSE_ACTIVE >= _SSE_LIMIT:
            return False
        _SSE_ACTIVE += 1
        return True


def sse_release() -> None:
    global _SSE_ACTIVE
    with _SSE_LOCK:
        _SSE_ACTIVE = max(0, _SSE_ACTIVE - 1)


def sse_active() -> int:
    """当前活跃的 SSE 流数量；健康检查与测试都靠它判断有没有泄漏。"""
    with _SSE_LOCK:
        return _SSE_ACTIVE


def make_base(deps):
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

    class BaseRoutes(BaseHTTPRequestHandler):
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
            mime = content_type.split(";")[0].strip().lower()
            headers = {"ETag": etag, "Cache-Control": cache, "Vary": "Accept-Encoding",
                       # 三件套：不许猜 MIME、不许被嵌进别人的 iframe、不外泄 Referer。
                       # 本地应用也一样——恶意页面用 iframe 套住本服务就能诱导点击。
                       "X-Content-Type-Options": "nosniff",
                       "X-Frame-Options": "DENY",
                       "Referrer-Policy": "no-referrer"}
            if mime == "text/html":
                # 页面全部资源都在本站：禁止外部脚本与表单提交，把注入后的利用面压到最小
                headers["Content-Security-Policy"] = (
                    "default-src 'self'; img-src 'self' data:; "
                    "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
                )

            inm = (self.headers.get("If-None-Match") or "").strip()
            if inm and inm.replace("W/", "") == etag.replace("W/", ""):
                self.send_response(304)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                return

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
        def _send_bytes(self, code: int, data: bytes, content_type: str,
                        extra_headers: dict | None = None,
                        cache: str = "private, max-age=300") -> None:
            """二进制响应。

            不复用 `_send`：那条路径会把 body 当字符串做 UTF-8 编码、还要判断能否 gzip，
            图片走一遍会直接坏掉。

            SVG 单独加 CSP + sandbox：用户在地址栏直接打开 `/assets/x.svg` 时，
            文件里的 `<script>` 是**同源**执行的——等于给了它调用本服务接口的权限。
            `<img>` 里不会执行，但「直接在浏览器打开」是最常见的操作，必须挡住。
            """
            headers = {"Content-Type": content_type,
                       "Content-Length": str(len(data)),
                       "Cache-Control": cache,
                       "X-Content-Type-Options": "nosniff"}
            if content_type.startswith("image/svg"):
                headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
            for key, value in (extra_headers or {}).items():
                headers[key] = str(value)
            self.send_response(code)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    self.close_connection = True
        def _no_content(self, code: int = 202) -> None:
            """无正文响应。MCP 规范里通知类请求必须回 202 且不带 body，
            编造成 `200 {}` 会让客户端以为收到了一条合法响应。
            """
            self.send_response(code)
            self.send_header("Content-Length", "0")
            self.end_headers()
        def _sse_open(self, hello: bool = True) -> bool:
            """开一条 SSE 流：不带 Content-Length，靠关闭连接收尾。

            流式响应的长度事先未知，用 chunked 又要客户端支持分块解析；
            `Connection: close` 对本地单进程最简单且被所有客户端接受。
            `hello=False` 用于「发一条就关」的短流：首帧注释是长连接保活用的，
            短流里多这么一行只会让 strict 客户端多解析一次。
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            for key, value in (self._cors_headers() or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.close_connection = True
            return self._sse_raw(": connected\n\n") if hello else True
        def _sse_raw(self, text: str) -> bool:
            """写一段原始 SSE 文本；返回 False 表示对端已断开。

            断开只在写的时候才暴露，所以每个发送点都要看返回值立即退出——
            否则循环会对着一个死连接继续跑满整个时长。
            """
            try:
                self.wfile.write(text.encode("utf-8"))
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                self.close_connection = True
                return False
        def _sse_event(self, payload, event: str = "message") -> bool:
            """发一条 SSE 消息。JSON 一定单行（`ensure_ascii=False` 不引入换行），
            否则 `data:` 后面的换行会被客户端当成帧结束。
            """
            data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
            return self._sse_raw(f"event: {event}\ndata: {data}\n\n")
        def _redirect(self, location: str, code: int = 302) -> None:
            """旧页面入口保留 302：书签与外部链接不 404，但不重复渲染两份内容。"""
            self.send_response(code)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        def _client(self) -> str:
            return self.client_address[0] if self.client_address else "unknown"
        def _error_text(self, exc: Exception, prefix: str = "服务端异常") -> str:
            """异常详情默认不回传：消息里常带绝对路径与内部端点。

            排查问题时设 `DEBUG=on` 才带上原文；平时只给异常类型，正文进服务端日志。
            """
            if pipe.settings.debug:
                return f"{prefix}：{type(exc).__name__}: {exc}"
            return f"{prefix}：{type(exc).__name__}（详情见服务端日志，设 DEBUG=on 可显示）"
        def _is_admin(self) -> bool:
            token = pipe.settings.admin_token
            if token:
                return safe_equal(self.headers.get("X-Admin-Token", ""), token)
            return self._client() in ("127.0.0.1", "::1")
        def _auto_approve(self) -> bool:
            """KB_APPROVAL=off 全放行；on 全审批；auto 仅本机管理员直通。"""
            mode = (pipe.settings.kb_approval or "auto").strip().lower()
            if mode == "off":
                return True
            if mode == "on":
                return False
            return self._is_admin()
        def _guard(self, method: str, path: str) -> bool:
            """所有请求的唯一入口闸门：Host → 鉴权等级 → 来源/内容类型。

            鉴权等级不再由各 handler 自己判断，统一查 `src/routing.py` 的表。
            这样「新增接口忘了加鉴权」不会再发生——漏登记只会让接口默认要 Key。
            OPTIONS 只校 Host：浏览器预检不带 Key，拦了就连正常跨域都做不了。
            """
            if self._host_gate():
                return True
            verb = method.upper()
            if verb == "OPTIONS":
                return False
            level = routing.level_for(path)
            if level == routing.ADMIN and not self._is_admin():
                metrics.inc("rag_unauthorized_total")
                guards.audit.write("request.forbidden", client=self._client(),
                                   path=path[:160], reason="admin_required")
                self._json({"ok": False, "error": "forbidden",
                            "message": "需要管理员权限（本机访问或带 X-Admin-Token）"}, 403)
                return True
            if verb in ("GET", "HEAD"):
                # 读请求同样按表：/api/source 返回整段原文、/api/trace 返回用户提问，
                # 只因为方法是 GET 就放行，等于把语料和提问记录公开。
                if level == routing.API and api_keys.enabled:
                    return self._require_key(path, "read.unauthorized")
                return False
            return self._write_gate(path)
        def _require_key(self, path: str, action: str) -> bool:
            """配了 API_KEYS 就必须带有效 Key；未配置时直接放行（单机默认形态）。"""
            _name, err = self._api_auth()
            if not err:
                return False
            metrics.inc("rag_unauthorized_total")
            guards.audit.write(action, client=self._client(),
                               path=path[:160], reason=err)
            self._json({"ok": False, "error": "unauthorized",
                        "message": "需要 API Key：Authorization: Bearer <key> 或 X-API-Key"},
                       401, {"WWW-Authenticate": 'Bearer realm="jiyi"'})
            return True
        def _host_gate(self) -> bool:
            """Host 必须是本机：挡 DNS rebinding，也挡反代把外部请求伪装成本机。

            为什么读请求也要拦：rebinding 之后页面与 API 同源，GET 的响应可以直接被读走，
            只保护写请求会漏掉「整库原文被拖走」。
            """
            reason = security.read_problem(self.headers)
            if not reason:
                return False
            metrics.inc("rag_host_rejected_total")
            guards.audit.write("request.rejected", client=self._client(),
                               path=self.path[:160], reason=reason)
            self._json({"ok": False, "error": "host_not_allowed",
                        "message": security.REASONS[reason]}, 403)
            return True
        def _write_gate(self, path: str) -> bool:
            """写请求的第二道闸：来源 + 内容类型，再按配置决定是否要 Key。

            `/api/ask*` 的鉴权留在 `_ask_preflight` 里做——那里还要记账与限流，
            在这里拦会让审计日志少一半信息。
            """
            try:
                has_body = int(self.headers.get("Content-Length") or 0) > 0
            except ValueError:
                has_body = True
            reason = security.write_problem(self.headers, has_body)
            if reason:
                metrics.inc("rag_write_rejected_total", {"reason": reason})
                guards.audit.write("write.rejected", client=self._client(),
                                   path=path[:160], reason=reason)
                self._json({"ok": False, "error": reason,
                            "message": security.REASONS[reason]},
                           415 if reason == "content_type" else 403)
                return True
            # 表里登记为 api 的写接口，配了 Key 就必须带。
            # `/api/ask` 与 `/api/ask/stream` 例外：它们在 `_ask_preflight` 里鉴权，
            # 那里还要记账与限流，提前拦会让审计日志少一半信息。
            # 必须列全名而不是按前缀放过：写成 startswith("/api/ask") 的话，
            # 将来新加一个没做 preflight 的 `/api/ask-batch` 就是裸接口。
            if (routing.level_for(path) == routing.API
                    and path not in ASK_PATHS_NO_KEY_GATE):
                return self._require_key(path, "write.unauthorized")
            return False
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
        def _cors_headers(self) -> dict:
            """跨域默认关闭；NOTES_CORS=* 或来源白名单才放行，个人笔记不该随便被网页读。"""
            raw = (os.environ.get("NOTES_CORS") or "").strip()
            if not raw:
                return {}
            origin = (self.headers.get("Origin") or "").strip()
            if raw == "*":
                allow = "*"
            elif origin and origin in [item.strip() for item in raw.split(",") if item.strip()]:
                allow = origin
            else:
                return {}
            return {
                "Access-Control-Allow-Origin": allow,
                "Access-Control-Allow-Headers": "Content-Type, Authorization, X-API-Key",
                "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
                "Access-Control-Max-Age": "600",
            }
        def _api_target(self, parsed) -> str:
            """把路径归到哪一组接口：notes / threads / files / settings，其余空串。"""
            path = parsed.path
            if path == "/api/notes" or path.startswith("/api/notes/"):
                return "notes"
            if path == "/api/threads" or path.startswith("/api/threads/"):
                return "threads"
            if path.startswith("/api/files/"):
                return "files"
            if path == "/api/settings" or path.startswith("/api/settings/"):
                return "settings"
            return ""
        def do_PUT(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            target = self._api_target(parsed)
            if self._guard("PUT", parsed.path):
                return
            if target not in ("threads", "files"):
                self._json({"error": "not found"}, 404)
                return
            body, err = self._read_note_body()
            if err:
                self._json({"ok": False, "error": "invalid_argument", "message": err}, 400)
                return
            handler = self._threads if target == "threads" else self._files
            handler("PUT", parsed.path, parse_qs(parsed.query), body)
        def do_PATCH(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            target = self._api_target(parsed)
            if self._guard("PATCH", parsed.path):
                return
            if target not in ("notes", "threads"):
                self._json({"error": "not found"}, 404)
                return
            body, err = self._read_note_body()
            if err:
                self._json({"ok": False, "error": "invalid_argument", "message": err}, 400)
                return
            handler = self._notes if target == "notes" else self._threads
            handler("PATCH", parsed.path, parse_qs(parsed.query), body)
        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            target = self._api_target(parsed)
            if self._guard("DELETE", parsed.path):
                return
            if target not in ("notes", "threads"):
                self._json({"error": "not found"}, 404)
                return
            body = None
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                length = 0
            if length > 0:
                body, err = self._read_note_body()
                if err:
                    self._json({"ok": False, "error": "invalid_argument", "message": err}, 400)
                    return
            handler = self._notes if target == "notes" else self._threads
            handler("DELETE", parsed.path, parse_qs(parsed.query), body)
        def do_OPTIONS(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            target = self._api_target(parsed)
            if self._guard("OPTIONS", parsed.path):
                return
            if not target:
                self._json({"error": "not found"}, 404)
                return
            handler = {"notes": self._notes, "threads": self._threads,
                       "files": self._files, "settings": self._settings}[target]
            handler("OPTIONS", parsed.path, parse_qs(parsed.query), None)
        def log_message(self, fmt: str, *args) -> None:
            pass

    return BaseRoutes
