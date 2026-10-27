"""桌面客户端用的 HTTP 层：不依赖浏览器，也不依赖 Tkinter。

为什么单独一层：界面代码没法在 CI 里跑，但「接口调得对不对」必须能被测试。
所有网络细节（超时、错误映射、编码）都收在这里，Tkinter 只负责画。

约定与 Web 前端完全一致：JSON 写请求、`base_rev` 乐观锁、错误码原样抛出。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8000"
READ_TIMEOUT = 15.0
ASK_TIMEOUT = 120.0
SYNC_TIMEOUT = 300.0


class ClientError(RuntimeError):
    """把服务端的结构化错误搬成异常，界面直接展示 message 即可。"""

    def __init__(self, message: str, status: int = 0, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code

    @property
    def is_offline(self) -> bool:
        return self.status == 0


class Client:
    def __init__(self, base: str = DEFAULT_BASE, api_key: str = ""):
        self.base = (base or DEFAULT_BASE).rstrip("/")
        self.api_key = (api_key or "").strip()
        # 系统代理会把 127.0.0.1 也当外网转发，返回 502，错误信息还跟真实原因无关。
        # 本机地址必须直连：这和 embeddings 里对本地推理端点的处理是同一个坑。
        host = (urllib.parse.urlparse(self.base).hostname or "").lower()
        loopback = (host in ("localhost", "::1", "[::1]") or host.startswith("127."))
        self._opener = (urllib.request.build_opener(urllib.request.ProxyHandler({}))
                        if loopback else None)

    # ---------- 底层 ----------
    def _request(self, method: str, path: str, body: dict | None = None,
                 query: dict | None = None, timeout: float = READ_TIMEOUT) -> dict:
        url = self.base + path
        if query:
            pairs = [(k, str(v)) for k, v in query.items() if v is not None]
            if pairs:
                url += "?" + urllib.parse.urlencode(pairs)
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        opener = self._opener.open if self._opener is not None else urllib.request.urlopen
        try:
            with opener(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            payload = {}
            try:
                payload = json.loads(exc.read().decode("utf-8", "replace"))
            except (ValueError, OSError):
                payload = {}
            message = payload.get("message") or payload.get("error") or f"HTTP {exc.code}"
            raise ClientError(str(message)[:300], exc.code,
                              str(payload.get("error") or "")) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ClientError(f"连不上服务（{reason}）。请先启动：python -m src.server",
                              0, "offline") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ClientError("服务返回的不是 JSON，请确认地址是否正确", 0, "bad_response") from exc

    # ---------- 读 ----------
    def health(self) -> dict:
        return self._request("GET", "/api/health")

    def settings(self) -> dict:
        return self._request("GET", "/api/settings")

    def update_settings(self, patch: dict) -> dict:
        return self._request("POST", "/api/settings", body=patch)

    def notes(self, limit: int = 200) -> list[dict]:
        return self._request("GET", "/api/notes", query={"limit": limit}).get("items", [])

    def note(self, note_id: str) -> dict:
        return self._request("GET", f"/api/notes/{urllib.parse.quote(note_id)}")

    def threads(self, limit: int = 60) -> list[dict]:
        return self._request("GET", "/api/threads", query={"limit": limit}).get("items", [])

    def thread(self, thread_id: str) -> dict:
        return self._request("GET", f"/api/threads/{urllib.parse.quote(thread_id)}").get("thread", {})

    def read_file(self, path: str) -> dict:
        return self._request("GET", "/api/files/raw", query={"path": path})

    def backups(self) -> list[dict]:
        return self._request("GET", "/api/storage/backups").get("items", [])

    # ---------- 写 ----------
    def ask(self, query: str, session_id: str | None = None) -> dict:
        body = {"query": query}
        if session_id:
            body["session_id"] = session_id
        return self._request("POST", "/api/ask", body=body, timeout=ASK_TIMEOUT)

    def save_note(self, question: str, answer: str, title: str = "") -> dict:
        """把一轮问答存成笔记；`from=chat` 与服务端「储存对话内容」开关语义一致。"""
        body = {
            "from": "chat",
            "messages": [
                {"role": "user", "text": question},
                {"role": "assistant", "text": answer},
            ],
        }
        if title.strip():
            body["title"] = title.strip()
        return self._request("POST", "/api/notes", body=body, timeout=READ_TIMEOUT)

    def write_file(self, path: str, content: str, base_rev: str = "") -> dict:
        body = {"path": path, "content": content}
        if base_rev:
            body["base_rev"] = base_rev
        return self._request("PUT", "/api/files/raw", body=body)

    def create_note_file(self, path: str, content: str) -> dict:
        return self._request("PUT", "/api/files/raw",
                             body={"path": path, "content": content, "create": True})

    def open_folder(self) -> dict:
        return self._request("POST", "/api/files/open-folder", body={})

    def open_file(self, path: str) -> dict:
        return self._request("POST", "/api/files/open", body={"path": path})

    def backup(self, note: str = "") -> dict:
        return self._request("POST", "/api/storage/backup", body={"note": note},
                             timeout=SYNC_TIMEOUT)

    def restore(self, name: str, force: bool = False) -> dict:
        return self._request("POST", "/api/storage/restore",
                             body={"name": name, "force": bool(force)},
                             timeout=SYNC_TIMEOUT)
