"""笔记目录锁：陈旧清理与释放都不能误伤别人手里的锁。

为什么单独测这块：目录锁靠「mkdir 原子」实现互斥，但清理陈旧锁和释放锁
都要 rmtree。一旦删错对象，两个进程会同时认为自己持锁，直接写坏同一篇笔记。
这类问题在顺序测试里看不出来，必须构造「锁被换人」的时序。
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.notes.store import (  # noqa: E402
    LOCK_STALE_SECONDS, NoteStore, StoreBusy, _break_stale, _identity,
)

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def test_normal() -> None:
    print("正常加锁 / 释放")
    with tempfile.TemporaryDirectory() as tmp:
        store = NoteStore(tmp)
        lock_dir = Path(tmp) / ".lock"
        with store.lock():
            check("持锁期间目录存在", lock_dir.is_dir())
        check("释放后目录消失", not lock_dir.exists())


def test_release_keeps_foreign_lock() -> None:
    print("释放时不删别人的锁")
    with tempfile.TemporaryDirectory() as tmp:
        store = NoteStore(tmp)
        lock_dir = Path(tmp) / ".lock"
        with store.lock():
            # 模拟「我这一把被判定超时、被别人清掉并重建」
            os.rename(lock_dir, Path(tmp) / ".lock.gone")
            os.mkdir(lock_dir)
            foreign = _identity(lock_dir)
        check("别人的锁还在", lock_dir.is_dir(), "被误删了")
        check("没被换成别人的", _identity(lock_dir) == foreign)
        # 这里只该动自己那把：改名出来的旧目录不归 store 管，删了就是越界
        check("没动别人的目录", (Path(tmp) / ".lock.gone").is_dir())


def test_break_stale() -> None:
    print("陈旧锁能被清理")
    with tempfile.TemporaryDirectory() as tmp:
        lock_dir = Path(tmp) / ".lock"
        os.mkdir(lock_dir)
        old = time.time() - LOCK_STALE_SECONDS - 10
        os.utime(lock_dir, (old, old))
        store = NoteStore(tmp)
        with store.lock():
            check("陈旧的被清掉并重新拿到锁", lock_dir.is_dir())
        check("退出后释放干净", not lock_dir.exists())


def test_break_stale_puts_back_foreign() -> None:
    print("清理陈旧锁时抢到别人的新锁要放回去")
    with tempfile.TemporaryDirectory() as tmp:
        lock_dir = Path(tmp) / ".lock"
        os.mkdir(lock_dir)
        stale = _identity(lock_dir)

        # 让第一次身份查询返回「刚才那把陈旧的」，rename 之后再返回真实身份，
        # 复现「判定陈旧 → 期间被重建 → 此刻 rename 拿到的是新锁」的时序。
        import src.notes.store as store_mod
        calls = {"n": 0}
        real = store_mod._identity

        def fake(path):
            calls["n"] += 1
            if calls["n"] == 1:
                return stale
            return real(path)

        store_mod._identity = fake
        try:
            os.rename(lock_dir, Path(tmp) / ".lock.other")
            os.mkdir(lock_dir)
            foreign = real(lock_dir)
            _break_stale(lock_dir)
        finally:
            store_mod._identity = real

        check("新锁被放回原位", lock_dir.is_dir(), "被当成陈旧锁删了")
        check("放回的是同一个目录", _identity(lock_dir) == foreign)


def test_busy() -> None:
    print("拿不到锁要报错而不是死等")
    with tempfile.TemporaryDirectory() as tmp:
        store = NoteStore(tmp)
        lock_dir = Path(tmp) / ".lock"
        os.mkdir(lock_dir)  # 崭新的锁：不该被当成陈旧清掉
        started = time.monotonic()
        try:
            with store.lock(timeout=0.3):
                pass
            check("应该抛 StoreBusy", False, "居然拿到了锁")
        except StoreBusy:
            spent = time.monotonic() - started
            check("超时后抛 StoreBusy", True)
            check("等待时间接近 timeout", 0.25 <= spent <= 2.0, f"{spent:.2f}s")
        check("新锁没被误清", lock_dir.is_dir())


def test_mutual_exclusion() -> None:
    print("多线程真互斥")
    with tempfile.TemporaryDirectory() as tmp:
        store = NoteStore(tmp)
        state = {"inside": 0, "max": 0, "n": 0}
        lock = threading.Lock()
        errors: list[str] = []

        def worker() -> None:
            try:
                with store.lock(timeout=10):
                    with lock:
                        state["inside"] += 1
                        state["n"] += 1
                        state["max"] = max(state["max"], state["inside"])
                    time.sleep(0.01)
                    with lock:
                        state["inside"] -= 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        check("没有报错", not errors, str(errors[:2]))
        check("8 个线程都进去了", state["n"] == 8, str(state["n"]))
        check("同一时刻只有 1 个持锁", state["max"] == 1, f"max={state['max']}")
        check("最终释放干净", not (Path(tmp) / ".lock").exists())


def main() -> int:
    test_normal()
    test_release_keeps_foreign_lock()
    test_break_stale()
    test_break_stale_puts_back_foreign()
    test_busy()
    test_mutual_exclusion()
    print(f"\n{'全部通过' if FAILED == 0 else f'{FAILED} 项失败'}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
