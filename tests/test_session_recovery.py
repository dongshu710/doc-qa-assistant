"""会话上下文：内存窗口 + 磁盘回填 + 清空墓碑。

守五条：
1. 内存里有就直接用，不去碰磁盘（回填是兜底不是主路径）；
2. 内存里没有（比如进程刚重启）能按 sid 从会话文件回填最近几轮；
3. 「清空上下文」之后不许被回填复活——用户点了清空就该是清空；
4. 回填只取问句，且不超过上下文窗口；
5. 磁盘读不出来 / 会话文件坏了，退回「没有上下文」，不许把提问打挂。

不联网、不起服务。
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.sessions import SessionStore, Turn  # noqa: E402
from src.threadstore import ThreadStore  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def test_memory_first() -> None:
    print("内存命中就不回填")
    calls: list[str] = []
    store = SessionStore(max_turns=3, loader=lambda sid: (calls.append(sid), ["磁盘上的旧问题"])[1])
    store.append("s1", "内存里的新问题", "答案")
    history = store.history("s1")
    check("拿到的是内存里的", [turn.query for turn in history] == ["内存里的新问题"],
          str([turn.query for turn in history]))
    check("没有触发回填", calls == [], str(calls))


def test_backfill() -> None:
    print("内存空了就按 sid 回填")
    calls: list[str] = []
    def loader(sid: str) -> list[str]:
        calls.append(sid)
        return ["稳盈系列起购金额是多少", "那赎回费呢"]
    store = SessionStore(max_turns=3, loader=loader)
    history = store.history("s2")
    check("回填出两轮", [turn.query for turn in history] == ["稳盈系列起购金额是多少", "那赎回费呢"],
          str([turn.query for turn in history]))
    check("第一次查询触发了一次回填", calls == ["s2"], str(calls))
    store.history("s2")
    check("第二次不再回填（已进内存）", calls == ["s2"], str(calls))
    check("回填的轮次不带答案", all(turn.answer == "" for turn in history),
          str([turn.answer for turn in history]))


def test_clear_tombstone() -> None:
    print("清空之后不许被回填复活")
    store = SessionStore(max_turns=3, loader=lambda sid: ["很久以前的问题"])
    store.history("s3")                      # 先回填一次
    check("清空前有上下文", len(store.history("s3")) == 1, "")
    store.clear("s3")
    check("清空后立刻为空", store.history("s3") == [], str(store.history("s3")))
    # 再查一次也不该从磁盘复活
    check("再次查询仍为空", store.history("s3") == [], str(store.history("s3")))


def test_ttl_allows_backfill_again() -> None:
    print("墓碑过期后才允许再次回填")
    store = SessionStore(max_turns=3, ttl_s=1, loader=lambda sid: ["旧问题"])
    store.clear("s4")
    check("墓碑生效期内为空", store.history("s4") == [], "")
    time.sleep(1.1)
    check("过期后可以回填", [turn.query for turn in store.history("s4")] == ["旧问题"],
          str(store.history("s4")))


def test_window_and_errors() -> None:
    print("回填受窗口限制，出错只退回空上下文")
    store = SessionStore(max_turns=2, loader=lambda sid: ["问1", "问2", "问3", "问4"])
    history = store.history("s5")
    check("只保留最近 2 轮", [turn.query for turn in history] == ["问3", "问4"],
          str([turn.query for turn in history]))

    def boom(sid: str):
        raise OSError("磁盘掉了")
    broken = SessionStore(loader=boom)
    check("loader 抛错时返回空", broken.history("s6") == [], str(broken.history("s6")))
    check("空 session_id 不调用 loader", SessionStore(loader=boom).history("") == [], "")


def test_threadstore_lookup(tmp: str) -> None:
    print("线程存储能按 sid 取出最近的问句")
    home = Path(tmp) / "home"
    store = ThreadStore(home)
    store.put("aaaaaa", {"title": "理财", "sid": "sid-a",
                         "turns": [{"q": "稳盈起购金额", "ts": "2026-11-10T10:00:00Z"},
                                   {"q": "那赎回费呢", "ts": "2026-11-10T10:01:00Z"}]})
    store.put("bbbbbb", {"title": "别的", "sid": "sid-b",
                         "turns": [{"q": "无关问题", "ts": "2026-11-10T10:02:00Z"}]})
    got = store.queries_for_sid("sid-a")
    check("按 sid 找到对应问句", got == ["稳盈起购金额", "那赎回费呢"], str(got))
    check("别的 sid 互不干扰", store.queries_for_sid("sid-b") == ["无关问题"],
          str(store.queries_for_sid("sid-b")))
    check("不存在的 sid 返回空", store.queries_for_sid("sid-none") == [], "")
    check("限制条数生效", store.queries_for_sid("sid-a", 1) == ["那赎回费呢"],
          str(store.queries_for_sid("sid-a", 1)))

    # 坏文件不能让整个回填失效
    bad = home / "threads" / "cccccc.json"
    bad.write_text("{ 这不是合法 JSON", encoding="utf-8")
    check("有坏文件时仍能返回", store.queries_for_sid("sid-a") == ["稳盈起购金额", "那赎回费呢"],
          str(store.queries_for_sid("sid-a")))


def test_end_to_end(tmp: str) -> None:
    """进程重启的等效场景：先写会话文件，再用全新的 SessionStore 取上下文。"""
    print("重启后追问不失忆（端到端）")
    home = Path(tmp) / "home2"
    threads = ThreadStore(home)
    threads.put("dddddd", {"title": "理财", "sid": "sid-d",
                           "turns": [{"q": "稳盈系列产品的起购金额是多少", "ts": "2026-11-10T10:00:00Z"}]})
    fresh = SessionStore(max_turns=3, loader=lambda sid: threads.queries_for_sid(sid, 3))
    history = fresh.history("sid-d")
    check("新进程能拿到上一轮", [turn.query for turn in history] == ["稳盈系列产品的起购金额是多少"],
          str([turn.query for turn in history]))

    from src.pipeline import _contextual_query  # noqa: PLC0415
    rewritten = _contextual_query(history, "那赎回费呢")
    check("追问被改写成可检索的问题",
          rewritten == "稳盈系列产品的起购金额是多少 那赎回费呢", rewritten)


def main() -> int:
    test_memory_first()
    test_backfill()
    test_clear_tombstone()
    test_ttl_allows_backfill_again()
    test_window_and_errors()
    with tempfile.TemporaryDirectory() as tmp:
        test_threadstore_lookup(tmp)
        test_end_to_end(tmp)
    print()
    if FAILED:
        print(f"SESSION RECOVERY FAILED: {FAILED}")
        return 1
    print("SESSION RECOVERY OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
