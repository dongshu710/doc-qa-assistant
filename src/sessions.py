"""会话上下文：只保留最近几轮，内存 TTL + LRU，避免历史无限增长。

为什么多轮要单独一层：
- 检索器只认「一个问题」，追问「那 R2 呢」单独看是域外问题；
- 上下文只用于**改写检索问题**，护栏与引用仍按当前问题校验；
- 会话不能无限存：默认 3 轮、30 分钟过期、最多 1000 个会话。

这里的 3 轮与 `threadstore.MAX_TURNS`（500 轮）不是矛盾，是两件事：
500 是「磁盘上一条对话最多留多少轮」，属于记录；
3 是「改写这次提问时参考几轮」，属于上下文窗口。
把 500 轮全塞进 prompt 既贵又会让改写跑偏。

多实例部署时会话需要外置（Redis）；当前实现是单实例内存，边界写在 README。
进程重启后内存为空，但 `loader` 会从磁盘会话按 sid 回填最近几轮，追问不会失忆。
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
    """会话上下文。内存里只留最近几轮，miss 时可以从磁盘会话回填。

    为什么要有回填：追问改写只需要「上一轮问的是什么」，而那句话本来就存在
    `threads/<id>.json` 里。进程重启后内存空了，但用户点开侧栏的同一条对话
    继续问，上下文不该凭空消失——那是把「重启」当成「失忆」。
    """

    def __init__(self, max_turns: int = 3, ttl_s: int = 1800, max_sessions: int = 1000,
                 loader=None):
        self.max_turns = max(1, int(max_turns))
        self.ttl_s = max(1, int(ttl_s))
        self.max_sessions = max(1, int(max_sessions))
        self._items: OrderedDict[str, tuple[float, list[Turn]]] = OrderedDict()
        self._lock = threading.Lock()
        # loader(session_id) -> list[str]，返回该会话最近的提问。由组合根注入，
        # 免得会话层反过来依赖线程存储（那会把两个包的加载顺序绑死）。
        self._loader = loader

    def set_loader(self, loader) -> None:
        """换一个回填来源。换了就清空内存快照：旧快照可能来自另一个存储区。"""
        self._loader = loader
        with self._lock:
            self._items.clear()

    def _alive(self, expires: float, now: float) -> bool:
        return expires > now

    def _remember(self, session_id: str, turns: list[Turn]) -> None:
        self._items[session_id] = (time.monotonic() + self.ttl_s, turns[-self.max_turns:])
        self._items.move_to_end(session_id)
        while len(self._items) > self.max_sessions:
            self._items.popitem(last=False)

    def history(self, session_id: str | None) -> list[Turn]:
        if not session_id:
            return []
        now = time.monotonic()
        with self._lock:
            item = self._items.get(session_id)
            if item:
                expires, turns = item
                if self._alive(expires, now):
                    self._items.move_to_end(session_id)
                    return list(turns)
                self._items.pop(session_id, None)
            loader = self._loader
        if loader is None:
            return []
        # 锁外调用：回填要扫磁盘上的会话文件，持锁会把并发的提问全卡住
        try:
            questions = list(loader(session_id) or [])
        except Exception:  # noqa: BLE001 —— 磁盘读不出来就当作没有上下文
            return []
        turns = [Turn(query=str(text)[:300], answer="", ts=time.time())
                 for text in questions if str(text).strip()]
        if not turns:
            return []
        with self._lock:
            # 期间可能已经有人写入更新的一轮，别把新的盖掉
            if session_id not in self._items:
                self._remember(session_id, turns)
            stored = self._items[session_id][1]
        return list(stored)

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
        """清空上下文，但留一个空条目当墓碑。

        直接删掉的话，下一次 `history()` 会从磁盘把历史重新捞回来——
        用户点了「清空上下文」却发现追问还记得上一轮，比没有这个按钮更糟。
        墓碑随 TTL 过期，届时才可能再次回填。
        """
        if not session_id:
            return
        with self._lock:
            self._items[session_id] = (time.monotonic() + self.ttl_s, [])
            self._items.move_to_end(session_id)
            while len(self._items) > self.max_sessions:
                self._items.popitem(last=False)

    def status(self) -> dict:
        now = time.monotonic()
        with self._lock:
            alive = sum(1 for expires, _ in self._items.values() if expires > now)
        return {"sessions": alive, "max_sessions": self.max_sessions,
                "max_turns": self.max_turns, "ttl_s": self.ttl_s}
