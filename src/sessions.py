"""会话上下文：只保留最近几轮，内存 TTL + LRU，避免历史无限增长。

为什么多轮要单独一层：
- 检索器只认「一个问题」，追问「那 R2 呢」单独看是域外问题；
- 上下文只用于**改写检索问题**，护栏与引用仍按当前问题校验；
- 会话不能无限存：默认 3 轮、30 分钟过期、最多 1000 个会话。

多实例部署时会话需要外置（Redis）；当前实现是单实例内存，边界写在 README。
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass


@dataclass
class Turn:
    query: str
    answer: str
    ts: float


class SessionStore:
    def __init__(self, max_turns: int = 3, ttl_s: int = 1800, max_sessions: int = 1000):
        self.max_turns = max(1, int(max_turns))
        self.ttl_s = max(1, int(ttl_s))
        self.max_sessions = max(1, int(max_sessions))
        self._items: OrderedDict[str, tuple[float, list[Turn]]] = OrderedDict()
        self._lock = threading.Lock()

    def _alive(self, expires: float, now: float) -> bool:
        return expires > now

    def history(self, session_id: str | None) -> list[Turn]:
        if not session_id:
            return []
        now = time.monotonic()
        with self._lock:
            item = self._items.get(session_id)
            if not item:
                return []
            expires, turns = item
            if not self._alive(expires, now):
                self._items.pop(session_id, None)
                return []
            self._items.move_to_end(session_id)
            return list(turns)

    def append(self, session_id: str | None, query: str, answer: str) -> None:
        if not session_id or not query:
            return
        # 两个钟各司其职：Turn.ts 将来要给人看（导出/展示），必须是墙钟；
        # 过期时间只能看单调钟，否则用户改系统时间会让会话瞬间过期或永不过期。
        wall = time.time()
        now = time.monotonic()
        with self._lock:
            item = self._items.get(session_id)
            turns = list(item[1]) if item else []
            turns.append(Turn(query=query[:300], answer=(answer or "")[:500], ts=wall))
            self._items[session_id] = (now + self.ttl_s, turns[-self.max_turns:])
            self._items.move_to_end(session_id)
            while len(self._items) > self.max_sessions:
                self._items.popitem(last=False)

    def clear(self, session_id: str | None) -> None:
        if not session_id:
            return
        with self._lock:
            self._items.pop(session_id, None)

    def status(self) -> dict:
        now = time.monotonic()
        with self._lock:
            alive = sum(1 for expires, _ in self._items.values() if expires > now)
        return {"sessions": alive, "max_sessions": self.max_sessions,
                "max_turns": self.max_turns, "ttl_s": self.ttl_s}
