"""知识库目录监听：外部改了文件就自动重建索引。

为什么需要：知识库是磁盘上的普通 Markdown，用户完全可能用编辑器直接改
（这正是本项目「文件即数据」的卖点）。没有监听时，改完不重启服务，
答案会一直是旧版——属于最坏的一类故障：**不报错，只是错**。

为什么用轮询而不是操作系统的文件事件：
- 标准库没有跨平台的文件监听（inotify / FSEvents / ReadDirectoryChangesW 三套）；
- 引第三方库违背零依赖；
- 记录个数通常几十到几百，5 秒一次 `os.scandir` 的代价是微秒级。
轮询的固有延迟（最多一个间隔）在这里可以接受：条款改完到有人提问，中间通常远超 5 秒。

边界：
- 只看文件名、mtime、大小。**内容改了但三者都没变**（编辑器保留时间戳）时不会触发，
  这是有意取舍：为了抓这种情况要去读全文哈希，那才是真正的成本。
- 重建走 `reload_kb()`，它本身是增量的（切分与向量都按签名复用），
  所以「监听触发一次重建」不等于「重新付一次钱」。
"""
from __future__ import annotations

import os
import threading
import time

# 两次扫描的最小间隔。低于 2 秒没有意义：单次重建都不止这么久，
# 更密的轮询只会把「正在重建」的窗口反复踩到。
MIN_INTERVAL_S = 2.0
DEFAULT_INTERVAL_S = 5.0


def dir_signature(directory: str) -> tuple:
    """目录签名：文件名 + mtime_ns + size，按名字排序。

    不用 `os.listdir` + `getmtime`：两次系统调用比 `scandir` 多一倍，
    而这个函数会被定时调用。目录不存在时返回空元组（不抛错：重建期间目录可能短暂消失）。
    """
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return ()
    rows = []
    for entry in entries:
        try:
            if not entry.is_file():
                continue
            stat = entry.stat()
        except OSError:
            continue
        rows.append((entry.name, stat.st_mtime_ns, stat.st_size))
    rows.sort()
    return tuple(rows)


class KnowledgeWatcher(threading.Thread):
    """后台线程：目录签名变了就回调一次。

    `on_change` 在监听线程里同步执行，所以它必须自己保证不抛、不长时间阻塞
    （`reload_kb` 默认已经走后台重建，满足这个前提）。
    """

    def __init__(self, resolve_dir, on_change, interval: float = DEFAULT_INTERVAL_S,
                 on_error=None):
        super().__init__(name="kb-watch", daemon=True)
        self._resolve_dir = resolve_dir
        self._on_change = on_change
        self._on_error = on_error
        self.interval = max(MIN_INTERVAL_S, float(interval or DEFAULT_INTERVAL_S))
        self._stop = threading.Event()
        self._last: tuple | None = None
        self.reloads = 0
        self.last_error = ""

    def poll_once(self) -> bool:
        """扫一次；返回是否触发了重建。测试直接调它，不必等线程。"""
        try:
            current = dir_signature(self._resolve_dir())
        except Exception as exc:  # noqa: BLE001 —— 监听线程不许因为一次失败就死掉
            self.last_error = f"{type(exc).__name__}: {exc}"
            if self._on_error:
                self._on_error(self.last_error)
            return False
        if self._last is None:
            # 首次只记基线：启动时目录本来就「和上次不同」，那不该触发重建
            self._last = current
            return False
        if current == self._last:
            return False
        self._last = current
        try:
            self._on_change()
            self.reloads += 1
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            if self._on_error:
                self._on_error(self.last_error)
            return False
        return True

    def start(self) -> None:
        """先同步取一次基线，再起线程。

        为什么不能在 `run()` 里取：服务刚起来的前几秒用户完全可能就去改文件
        （比如「改完再问」的操作习惯）。如果基线是在第一次轮询时才取，
        那次修改会被当成「初始状态」直接吞掉，而且之后永远补不回来——
        症状是「我明明改了，重启一次才生效」，最难查的一类。
        """
        try:
            self._last = dir_signature(self._resolve_dir())
        except Exception as exc:  # noqa: BLE001 —— 目录暂时不可读不该阻止启动
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._last = None
        super().start()

    def run(self) -> None:
        # 用 Event.wait 而不是 sleep：stop() 能立刻生效，
        # 否则服务退出时最多要等一个完整间隔。
        while not self._stop.wait(self.interval):
            self.poll_once()

    def stop(self) -> None:
        self._stop.set()
