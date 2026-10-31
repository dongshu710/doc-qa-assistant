"""索引换代的竞态：命中不能跨代引用，锁不能误删别人的。

为什么单独测：这两处都只在「重建恰好插在读与用之间」时才出问题，
顺序执行的用例永远走不到。而它们的失败模式都很重——一个是整次问答
500，一个是两个进程同时写同一份数据。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import kbstore, locks  # noqa: E402
from src.keywords import Entry, Hit, MatchReport  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def make_pipeline(tmp: Path):
    (tmp / "kb").mkdir()
    (tmp / "kb" / "seed.md").write_text(
        "# 产品\n\n稳盈系列起购金额为 1 元。\n\n## 期限\n\n封闭期 90 天。\n", encoding="utf-8")
    (tmp / "home").mkdir()
    os.environ.update({
        "APP_CONFIG": str(tmp / "app.json"), "NOTE_HOME": str(tmp / "home"),
        "SETUP_DONE": "1", "KB_STORE": "off", "KB_DIR": str(tmp / "kb"),
        "RETRIEVAL": "vector", "EMBEDDING_PROVIDER": "none", "API_KEYS": "",
        "KEYWORD_GUARD": "", "KEYWORD_MODE": "on",
    })
    from src.server import create_server
    _httpd, pipe = create_server("127.0.0.1", 0, str(tmp / "kb"))
    return pipe


def test_stale_hits_fall_back(pipe) -> None:
    print("命中来自上一代索引 → 退回检索，不 500")
    entry = Entry(term="起购金额", doc_id="seed.md", title="产品", section="产品",
                  snippet="稳盈系列起购金额为 1 元。", kind="list", weight=1.0,
                  chunk_index=99999)          # 故意越界：模拟旧代索引的位置
    fake = MatchReport(hits=[Hit(entry, 1.0)], rejected=[], gate=None)
    real = pipe.keywords.match_report
    pipe.keywords.match_report = lambda _q: fake
    try:
        result = pipe.ask("起购金额是多少")
    finally:
        pipe.keywords.match_report = real
    check("整次问答没有抛异常", isinstance(result, dict), str(type(result)))
    check("留痕了 keyword_stale", result.get("keyword_stale") == 1, str(result.get("keyword_stale")))
    check("没有伪装成关键词直出", result.get("mode") != "keyword_local", str(result.get("mode")))
    check("引用都指得到原文",
          all(isinstance(c.get("chunk_index"), int) and c["chunk_index"] >= 0
              for c in (result.get("citations") or [])),
          str(result.get("citations"))[:200])


def test_rebuild_keywords_cas(pipe) -> None:
    print("重建关键词期间索引换代 → 丢弃结果，不覆盖新索引")
    real = pipe._make_keywords
    calls = {"n": 0}

    def wrapped(chunks, enrich):
        calls["n"] += 1
        if calls["n"] == 1:
            # 构造期间模拟全量重建：chunks 换成另一个 list 对象（同一批内容）
            pipe._swap_index(pipe.knowledge_dir, list(pipe.chunks),
                             pipe.retriever, pipe.keywords)
        return real(chunks, enrich)

    pipe._make_keywords = wrapped
    try:
        detail = pipe.rebuild_keywords(enrich=False)
    finally:
        pipe._make_keywords = real
    check("如实报了 skipped", detail.get("skipped") == "index_rebuilt", str(detail)[:200])
    check("计数进 rebuild_state", (pipe.rebuild_state().get("keywords_skipped") or 0) >= 1,
          str(pipe.rebuild_state()))


def test_file_lock(tmp: Path) -> None:
    print("知识库文件锁：陈旧清理与释放都不能误删别人的")
    lock_path = str(tmp / "kb" / "state.lock")

    with kbstore._FileLock(lock_path):
        check("持锁期间锁文件在", os.path.exists(lock_path))
    check("释放后锁文件消失", not os.path.exists(lock_path))

    # 模拟「我这把被判超时、被别人挪走并重建」：此时锁文件上已是别人的，
    # 我的身份对不上，释放时一个字都不能动。
    # 注意这里不能真去 rename 一个还开着 fd 的文件：Windows 会直接拒绝
    # （PermissionError），而这恰好也是 Windows 上的一层额外保护——
    # 持有者还活着时，别人连挪都挪不动。
    stale_holder = kbstore._FileLock(lock_path)
    stale_holder._identity = (0, 0)        # 一把已经不存在的旧锁
    Path(lock_path).write_text("999", encoding="utf-8")
    foreign = locks.identity(lock_path)
    stale_holder.__exit__(None, None, None)
    check("别人的新锁还在", os.path.exists(lock_path), "被误删了")
    check("没被换成别人的", locks.identity(lock_path) == foreign)

    # 身份对得上就正常删
    Path(lock_path).unlink()               # 先把上一步留下的「别人的锁」收掉
    mine = kbstore._FileLock(lock_path)
    with mine:
        pass
    check("自己那把照常释放", not os.path.exists(lock_path))

    # 陈旧锁能被清掉并重新拿到
    old_lock = kbstore._FileLock(lock_path)
    Path(lock_path).write_text("1", encoding="utf-8")
    stale_at = time.time() - old_lock.stale_s - 10
    os.utime(lock_path, (stale_at, stale_at))
    with old_lock:
        check("陈旧的被清掉并拿到锁", os.path.exists(lock_path))
        check("锁里写的是自己 pid",
              Path(lock_path).read_text(encoding="utf-8").strip() == str(os.getpid()))
    check("退出后清理干净", not os.path.exists(lock_path))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        pipe = make_pipeline(Path(tmp))
        test_stale_hits_fall_back(pipe)
        test_rebuild_keywords_cas(pipe)
        test_file_lock(Path(tmp))
    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
