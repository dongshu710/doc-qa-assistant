"""长任务：同步快速路径 / 转后台 / 轮询 / 名额上限。

这条链最容易出的错是「看起来异步了，其实结果丢了」：
返回 202 之后任务崩了没人知道，或者轮询永远拿不到 result。
所以这里两头都钉：单元层（registry 本身）与 HTTP 层（真起服务打一遍）。

`TASK_GRACE_S=0` 是刻意设的：不然「20 秒内跑完就走同步」这条默认路径会让
测试大概率跑不到异步分支，而异步分支才是新代码。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tasks import TaskBusy, TaskError, TaskRegistry  # noqa: E402

HOST = "127.0.0.1"
FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def request(port: int, path: str, payload: dict | None = None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"http://{HOST}:{port}{path}", data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    try:
        with opener.open(req, timeout=60) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, dict(exc.headers or {}), json.loads(body)
        except json.JSONDecodeError:
            return exc.code, dict(exc.headers or {}), {"raw": body[:200]}


def test_registry() -> None:
    print("任务表本身")
    registry = TaskRegistry(max_concurrent=2, grace_s=5.0)

    payload, deferred = registry.run_or_defer("fast", lambda: {"value": 42})
    check("快任务走同步路径（不产生任务记录）", deferred is False and payload["value"] == 42, str(payload))
    check("同步路径不登记任务", registry.list() == [], str(registry.list()))

    slow = TaskRegistry(max_concurrent=2, grace_s=0.0)
    payload, deferred = slow.run_or_defer("slow", lambda: (time.sleep(0.4), {"done": True})[1])
    check("慢任务转后台", deferred is True and payload.get("state") == "running", str(payload))
    task_id = payload.get("id")
    check("转后台时带 task_id", bool(task_id and task_id.startswith("t-")), str(task_id))

    deadline = time.monotonic() + 10
    state = {}
    while time.monotonic() < deadline:
        task = slow.get(task_id)
        state = task.payload() if task else {}
        if state.get("state") == "done":
            break
        time.sleep(0.05)
    check("轮询能拿到完成态与结果", state.get("state") == "done"
          and (state.get("result") or {}).get("done") is True, str(state))

    check("列表里能看到这条任务", any(item["id"] == task_id for item in slow.list()), str(slow.list()))

    # 失败：同步路径原样抛，异步路径记进 task.error
    boom = TaskRegistry(max_concurrent=2, grace_s=5.0)
    try:
        boom.run_or_defer("boom", lambda: (_ for _ in ()).throw(TaskError(404, {"error": "nope"})))
        check("同步路径把异常原样抛出", False, "没有抛异常")
    except TaskError as exc:
        check("同步路径保留状态码（404 不回成 500）", exc.status == 404, str(exc.status))

    def boom_later():
        # 先睡一下再炸：grace=0 时若任务瞬间结束，会走同步分支（抛给调用方），
        # 那样测的就不是「失败落到任务上」了。
        time.sleep(0.3)
        raise RuntimeError("炸了")

    boom2 = TaskRegistry(max_concurrent=2, grace_s=0.0)
    payload, _deferred = boom2.run_or_defer("boom2", boom_later)
    task_id = payload["id"]
    for _ in range(100):
        state = (boom2.get(task_id) or type("X", (), {"payload": lambda self: {}})()).payload()
        if state.get("state") != "running":
            break
        time.sleep(0.05)
    check("后台任务失败要落到任务上", state.get("state") == "error" and "炸了" in (state.get("error") or ""),
          str(state))
    check("失败任务不带 result", "result" not in state, str(state))

    # 名额上限
    busy = TaskRegistry(max_concurrent=1, grace_s=0.0)
    busy.run_or_defer("hold", lambda: (time.sleep(0.6), None)[1])
    try:
        busy.run_or_defer("second", lambda: None, grace_s=0.0)
        check("名额满时拒绝新任务", False, "居然接受了")
    except TaskBusy:
        check("名额满时抛 TaskBusy（调用方回 503）", True)


def test_http() -> None:
    print("HTTP 层：202 + 轮询")
    tmp = tempfile.mkdtemp(prefix="tasks_")
    home = Path(tmp) / "notes"
    env = {
        "KB_DIR": str(Path(tmp) / "kb"),
        "KB_SEED_DIR": str(ROOT / "data" / "demo"),
        "KB_APPROVAL": "off",
        "KEYWORD_INDEX": str(Path(tmp) / "kw.json"),
        "RETRIEVAL": "bm25",
        "QUERY_EXPANSION": "off",
        "MIN_SCORE": "0",
        "KEYWORD_MODE": "off",
        "LOG_DIR": str(Path(tmp) / "logs"),
        "RAW_DIR": str(Path(tmp) / "raw"),
        "ARTIFACTS_DIR": str(Path(tmp) / "artifacts"),
        "SETUP_DONE": "1",
        "APP_CONFIG": str(Path(tmp) / "app.json"),
        "EMBEDDING_PROVIDER": "none",
        "NOTE_HOME": str(home),
        # 0 = 一律走异步分支。默认 20 秒会让这条测试「有时同步有时异步」。
        "TASK_GRACE_S": "0",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY"):
        os.environ.pop(key, None)

    from src.server import create_server

    httpd, _pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def wait(task_id: str, timeout: float = 60.0) -> dict:
        deadline = time.monotonic() + timeout
        last = {}
        while time.monotonic() < deadline:
            status, _headers, body = request(port, f"/api/tasks/{task_id}")
            last = body
            if status == 200 and body.get("state") != "running":
                return body
            time.sleep(0.2)
        return last

    try:
        # 用 scope=all：`scope=docs` 在没有自动出题产物时是空集合，会走「没有可运行
        # 的用例」的同步早退分支，根本碰不到任务层。sleep 让每例慢一点，
        # 确保在 grace=0 下稳定走到 202。
        status, headers, body = request(port, "/api/cases/run",
                                        {"scope": "all", "sleep": 0.02})
        check("评测接口返回 202", status == 202, f"{status} {str(body)[:200]}")
        check("202 带 Location 指向任务", str(headers.get("Location", "")).startswith("/api/tasks/"),
              str(headers.get("Location")))
        task_id = str(body.get("id") or "")
        check("202 正文带 task_id 与 running", bool(task_id) and body.get("state") == "running",
              str(body)[:200])

        done = wait(task_id)
        check("轮询到 done", done.get("state") == "done", str(done)[:300])
        result = done.get("result") or {}
        check("结果里有评测统计", "total" in result and "pass_rate" in result, str(result)[:200])
        check("结果落盘（run_at 有值）", bool(result.get("run_at")), str(result)[:200])

        status, _headers, body = request(port, "/api/tasks")
        check("任务列表包含刚跑完的这条",
              any(item.get("id") == task_id for item in (body.get("items") or [])), str(body)[:200])

        status, _headers, body = request(port, "/api/tasks/t-nope")
        check("未知任务回 404 且说明原因", status == 404 and "不存在" in str(body.get("message")),
              f"{status} {str(body)[:160]}")

        # 空存储区备份会直接被拒（「还没有可备份的内容」是 400，不是 bug）。
        # 先写一条笔记，让备份有东西可打包——顺便验证 400 那条不会把任务标成 done。
        status, _headers, body = request(port, "/api/notes", {
            "title": "任务测试",
            "messages": [{"role": "user", "text": "任务测试：长任务备份用的笔记正文。"}],
        })
        check("先建一条笔记", status in (200, 201), f"{status} {str(body)[:160]}")

        status, headers, body = request(port, "/api/storage/backup", {"note": "task-test"})
        check("备份接口返回 202", status == 202, f"{status} {str(body)[:200]}")
        done = wait(str(body.get("id") or ""))
        check("备份任务完成", done.get("state") == "done", str(done)[:300])
        backed = (done.get("result") or {}).get("files")
        check("备份结果报出文件数", isinstance(backed, int) and backed >= 0, str(done.get("result"))[:200])
        exports = home / "exports" / "backups"
        check("备份真的落到存储区", exports.is_dir() and any(exports.iterdir()),
              str(exports))
    finally:
        httpd.shutdown()
        httpd.server_close()
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    test_registry()
    test_http()
    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("TASKS OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
