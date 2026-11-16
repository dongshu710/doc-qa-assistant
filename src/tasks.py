"""长任务：把「几十秒到几分钟的操作」从请求线程搬到后台，前端轮询取结果。

为什么需要：`/api/cases/run` 真模型跑一遍要几十秒到几分钟，大存储区备份同理。
它们跑在请求线程里，代价有三份：

1. 占着一个工作槽（共 64），压测或多人共用时，正常问答被这些慢活挤掉；
2. 浏览器与中间代理通常在 60s 左右掐断连接，用户看到「请求失败」，
   而服务端其实跑完了——白跑一次，结果也没人拿到；
3. 断开之后没有任何地方能查到它跑完没有。

两种取法（`run_or_defer`）：

- **同步快速路径**：先等 `grace_s`（默认 20s）。小库跑完就直接返回，
  前端不用改、审计里也不会多出一堆「任务」。这条路径是刻意留的：
  把所有调用都改成异步，等于让「备份 3 个文件」也要轮询一次。
- **异步**：超过 grace 就返回 task_id，任务在后台继续跑，前端轮询
  `GET /api/tasks/{id}`。

并发上限 2：这类操作是 CPU/磁盘密集，各自还会再开线程或进程。超限直接
503 + `Retry-After`——排队会让用户以为卡住了，而且排队期间请求仍占着工作槽，
等于把「忙」伪装成「慢」。

**不做**通用 `POST /api/tasks {action}` 派发：那等于给调用方一个「按名字执行内部
操作」的入口，白名单漏一个就是提权。现有端点自己决定要不要异步，边界更清楚。
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

DEFAULT_GRACE_S = 20.0
MAX_CONCURRENT = 2
TASK_TTL_S = 3600.0      # 完成后保留一小时：够前端轮询，也不会无限堆内存
MAX_KEEP = 50


class TaskBusy(RuntimeError):
    """并发名额已满。调用方据此回 503 + Retry-After。"""


class TaskError(Exception):
    """带 HTTP 状态码的任务失败。

    为什么需要：`backup.restore` 的「备份不存在」是 404、「文件被占用」是 409。
    统一成 500 会把「你选错了备份」说成「服务坏了」，调用方与用户都会走错方向。
    同步路径原样抛出这个异常，异步路径把它记进 `task.error`（状态码在轮询结果里
    没意义——那时请求早就结束了）。
    """

    def __init__(self, status: int, payload: dict):
        super().__init__(str(payload.get("message") or payload.get("error") or "任务失败"))
        self.status = int(status)
        self.payload = payload


@dataclass
class Task:
    id: str
    name: str
    state: str = "running"            # running | done | error
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    result: object = None
    error: str = ""

    def payload(self) -> dict:
        elapsed = (self.finished or time.monotonic()) - self.started
        out = {"ok": True, "id": self.id, "name": self.name, "state": self.state,
               "elapsed_ms": int(elapsed * 1000)}
        if self.state == "done":
            out["result"] = self.result
        elif self.state == "error":
            out["error"] = self.error
        return out


class TaskRegistry:
    """进程内的任务表。

    为什么不落盘：这些任务的结果本身已经落到磁盘（`report_doc_cases.json`、
    备份目录），任务表只是「这一次调用跑到哪了」的临时状态。进程重启后
    重跑一次即可，持久化反而要处理「重启后任务卡在 running」的假状态。
    """

    def __init__(self, max_concurrent: int = MAX_CONCURRENT,
                 grace_s: float = DEFAULT_GRACE_S):
        self.max_concurrent = max(1, int(max_concurrent))
        self.grace_s = max(0.0, float(grace_s))
        self._slots = threading.BoundedSemaphore(self.max_concurrent)
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    # ---------- 查询 ----------
    def get(self, task_id: str) -> Task | None:
        with self._lock:
            self._prune_locked()
            return self._tasks.get(task_id)

    def list(self, limit: int = 20) -> list[dict]:
        with self._lock:
            self._prune_locked()
            items = sorted(self._tasks.values(), key=lambda t: t.started, reverse=True)
            return [item.payload() for item in items[:max(1, int(limit))]]

    def active(self) -> int:
        """正在跑的任务数。`/api/health` 用它说明「慢」是因为在跑长任务。"""
        with self._lock:
            return sum(1 for task in self._tasks.values() if task.state == "running")

    def _prune_locked(self) -> None:
        now = time.monotonic()
        for key, task in list(self._tasks.items()):
            if task.state != "running" and now - (task.finished or now) > TASK_TTL_S:
                self._tasks.pop(key, None)
        if len(self._tasks) > MAX_KEEP:
            finished = sorted((t for t in self._tasks.values() if t.state != "running"),
                              key=lambda t: t.finished or 0)
            for task in finished[:max(0, len(self._tasks) - MAX_KEEP)]:
                self._tasks.pop(task.id, None)

    # ---------- 执行 ----------
    def run_or_defer(self, name: str, fn, grace_s: float | None = None):
        """跑 `fn`，最多同步等 `grace_s` 秒。

        返回 `(payload, deferred)`：
        - `deferred=False`：`payload` 就是 `fn()` 的返回值，调用方按老方式回 200；
        - `deferred=True`：`payload` 是任务描述，调用方回 202 + task_id。
        """
        grace = self.grace_s if grace_s is None else max(0.0, float(grace_s))
        if not self._slots.acquire(blocking=False):
            raise TaskBusy(f"同时运行的后台任务已达上限（{self.max_concurrent} 个），请稍后重试")
        task = Task(id="t-" + uuid.uuid4().hex[:12], name=name)
        box: dict = {}
        done = threading.Event()

        def worker() -> None:
            try:
                box["result"] = fn()
            except Exception as exc:  # noqa: BLE001 —— 任务失败要落到任务上，不能凭空消失
                box["exc"] = exc
                box["error"] = f"{type(exc).__name__}: {exc}"[:300]
            finally:
                with self._lock:
                    task.finished = time.monotonic()
                    if "error" in box:
                        task.state, task.error = "error", box["error"]
                    else:
                        task.state, task.result = "done", box["result"]
                done.set()
                self._slots.release()

        threading.Thread(target=worker, name=f"task-{name}", daemon=True).start()
        if done.wait(grace):
            if "exc" in box:
                # 原样抛出：调用方要按异常自己的语义回 404 / 409 / 500，
                # 包一层字符串就把状态码丢了。
                raise box["exc"]
            return box["result"], False

        with self._lock:
            self._tasks[task.id] = task
            self._prune_locked()
        return task.payload(), True
