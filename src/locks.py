"""跨进程锁的原子清理。

知识库版本目录、笔记、索引三处都要在同一份数据上互斥，各写一遍
「判定陈旧 → 删掉」很容易漏掉竞态：A 判定陈旧的同一瞬间，B 刚释放锁并
立刻重建，A 删掉的是 B 的新锁——于是 A、B 同时持锁写同一份数据。

这里统一成「先改名、再核对身份」：rename 是原子的，删的永远是改名后
落在自己手上那份；身份对不上就原样放回去，这次不清理。

两种形态共用一套：知识库是单个锁文件（O_EXCL 创建），笔记是锁目录
（mkdir 原子创建）。差异只在最后一步是删文件还是删目录。
"""

from __future__ import annotations

import os
import shutil
import time

# 陈旧阈值。30 秒太短：一次万级文件的大版本写入叠加杀软扫描可能超时，
# 被误判成残留后两个进程会同时写版本目录。默认放长到 2 分钟，
# 真卡死时最坏也就多等这么久。
STALE_DEFAULT_S = 120.0


def identity(path: str | os.PathLike) -> tuple[int, int] | None:
    """(inode, mtime_ns)。用于确认改名前后是不是同一个对象。"""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns)


def _morgue(path: str | os.PathLike) -> str:
    return f"{path}.stale-{os.getpid()}-{time.monotonic_ns()}"


def break_stale(path: str | os.PathLike, is_dir: bool = False) -> bool:
    """把陈旧的锁挪走并删掉。返回是否真的清掉了。

    改名前先记身份，改名后复核：若中途别人也处理过（或重建了新锁），
    核对不上就放回原处——宁可这次不清理，也不能删掉活锁。
    """
    before = identity(path)
    if before is None:
        return False
    morgue = _morgue(path)
    try:
        os.rename(path, morgue)
    except OSError:
        return False          # 别人已经处理掉了
    if identity(morgue) != before:
        try:
            os.rename(morgue, path)
        except OSError:
            pass
        return False
    if is_dir:
        shutil.rmtree(morgue, ignore_errors=True)
    else:
        try:
            os.remove(morgue)
        except OSError:
            pass
    return True


def age_s(path: str) -> float:
    """锁存在了多久。与文件系统 mtime 比较必须用墙钟，不能用 monotonic。"""
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return 0.0


def break_if_stale(path: str, threshold_s: float = STALE_DEFAULT_S,
                   is_dir: bool = False) -> bool:
    if not (os.path.exists(path)) or age_s(path) <= threshold_s:
        return False
    return break_stale(path, is_dir=is_dir)


def stale_threshold(env_name: str, default: float = STALE_DEFAULT_S) -> float:
    """读环境变量覆盖阈值；坏值回落到默认，别因为配错就永不清理或立刻清理。"""
    try:
        value = float(os.environ.get(env_name, "") or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default
