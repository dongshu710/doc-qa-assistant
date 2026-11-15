"""可观测性三项的回归：访问日志、停机落盘、指标标签与 trace 丢弃计数。

为什么不写在 test_server 里：这三条都不是「功能」，而是**出事时能不能查**。
它们坏掉时页面完全正常——访问日志一行不写、成本丢最后一秒、指标里分不清实例，
用户看到的只是「有一次答慢了，但是复现不了」。

跑法：python tests/test_observability.py
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import accesslog  # noqa: E402
from src.guards import CostBudget, Guards  # noqa: E402
from src.metrics_exporter import Metrics  # noqa: E402
from src.otel import TraceExporter  # noqa: E402

NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def prepare_home(tmp: Path) -> Path:
    work = tmp / "work"
    shutil.copytree(ROOT / "data", work / "data")
    cfg = work / "data" / "app.json"
    data = json.loads(cfg.read_text(encoding="utf-8")) if cfg.is_file() else {}
    data.setdefault("notes", {})["home"] = str(work / "notes")
    cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "notes").mkdir(parents=True, exist_ok=True)
    (work / "logs").mkdir(parents=True, exist_ok=True)
    return work


def env_for(work: Path, **extra: str) -> dict:
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": str(ROOT),
        "APP_CONFIG": str(work / "data" / "app.json"),
        "KB_DIR": str(work / "data" / "kb"),
        "RAW_DIR": str(work / "data" / "raw"),
        "LOG_DIR": str(work / "logs"),
        "SETUP_DONE": "1",
        "EMBEDDING_PROVIDER": "none",
    })
    env.update(extra)
    return env


def wait_up(port: int, timeout: float = 30.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with NO_PROXY.open(f"http://127.0.0.1:{port}/api/health", timeout=1) as resp:
                resp.read()
                return True
        except Exception:  # noqa: BLE001 —— 还没起来
            time.sleep(0.2)
    return False


def test_accesslog_unit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp)
        accesslog.emit(str(log_dir), method="GET", path="/api/ask?q=我的身份证号",
                       status=200, ms=12.34, client="127.0.0.1", req_id="r1")
        target = log_dir / "access.jsonl"
        check("写出一行", target.exists())
        if target.exists():
            record = json.loads(target.read_text(encoding="utf-8").splitlines()[-1])
            check("只记 path 不记 query", record["path"] == "/api/ask", record["path"])
            check("带状态码与耗时", record["status"] == 200 and record["ms"] == 12.3, str(record))
            check("带客户端与 req_id", record["client"] == "127.0.0.1" and record["req_id"] == "r1")

        os.environ["ACCESS_LOG"] = "off"
        try:
            accesslog.emit(str(log_dir), method="GET", path="/api/health",
                           status=200, ms=1.0, client="127.0.0.1")
            lines = target.read_text(encoding="utf-8").splitlines()
            check("ACCESS_LOG=off 时不再写", len(lines) == 1, str(len(lines)))
        finally:
            os.environ.pop("ACCESS_LOG", None)


def test_accesslog_http() -> None:
    """真起一次服务：证明 access log 是接在请求生命周期上的，不是死代码。"""
    with tempfile.TemporaryDirectory() as tmp:
        work = prepare_home(Path(tmp))
        port = free_port()
        proc = subprocess.Popen([sys.executable, "-m", "src.server", "--host", "127.0.0.1",
                                 "--port", str(port)], cwd=str(ROOT), env=env_for(work),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            if not wait_up(port):
                check("服务启动", False, "超时")
                return
            with NO_PROXY.open(f"http://127.0.0.1:{port}/ask?utm_source=test", timeout=10) as resp:
                resp.read()
            target = work / "logs" / "access.jsonl"
            for _ in range(30):
                if target.exists() and target.stat().st_size:
                    break
                time.sleep(0.1)
            rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()
                    if line.strip()] if target.exists() else []
            page = [r for r in rows if r["path"] == "/ask"]
            check("页面请求被记录", bool(page), f"{len(rows)} 行")
            if page:
                check("状态码 200", page[-1]["status"] == 200, str(page[-1]))
                check("耗时是正数", page[-1]["ms"] >= 0, str(page[-1]["ms"]))
                check("query 未落盘", all("utm_source" not in r["path"] for r in rows))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_metrics_labels() -> None:
    metrics = Metrics(enabled=True, service="svc-under-test")
    metrics.inc("rag_requests_total", {"behavior": "answer"})
    metrics.set_gauge("rag_sse_active", 2.0)
    metrics.observe("rag_latency_seconds", 0.4)
    text = metrics.render()
    check("counter 带 service", 'service="svc-under-test"' in text)
    check("counter 带 instance", "instance=" in text)
    check("gauge 带 service", text.count('service="svc-under-test"') >= 3,
          str(text.count('service="svc-under-test"')))
    check("直方图也带", 'rag_latency_seconds_bucket{' in text and "service=" in text)
    check("服务名不再写死 doc-qa", "doc-qa" not in text)


def test_otel_drop_metric() -> None:
    exporter = TraceExporter("http://127.0.0.1:1", "svc", 16)
    calls: list[int] = []
    exporter.on_drop = lambda: calls.append(1)
    # 手动把队列换成一个满的：不依赖线程调度，结果确定
    exporter._queue = queue.Queue(maxsize=1)
    exporter._queue.put_nowait({"dummy": True})
    exporter.emit("ask", time.time_ns(), {"k": "v"})
    check("队列满时 dropped 涨", exporter.dropped == 1, str(exporter.dropped))
    check("丢弃回调被调用", len(calls) == 1, str(len(calls)))


def test_cost_flush_on_shutdown() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp)
        budget = CostBudget(daily_limit=1000, path=str(log_dir / "cost.json"))
        budget.add(123)
        # 第一次 add 会立刻落一次（_last_save 初值 0），之后的 add 按 1s/50 次节流。
        # 这里只断言「flush 之后盘上的数字等于全部累计」，不假设节流的具体时机。
        budget.add(7)
        budget.flush()
        saved = json.loads((log_dir / "cost.json").read_text(encoding="utf-8"))
        check("flush 后落盘且计数完整", saved.get("tokens") == 130, str(saved))


def test_guards_shutdown() -> None:
    """Guards.shutdown() 必须把成本计数写下去——它原来没有任何调用点。"""
    from src.config import load_settings

    with tempfile.TemporaryDirectory() as tmp:
        guards = Guards(load_settings(), str(Path(tmp)))
        guards.cost.add(77)
        guards.shutdown()
        path = Path(tmp) / "cost.json"
        check("shutdown 后成本落盘", path.exists())
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            check("落盘用量正确", data.get("tokens") == 77, str(data))
        guards.shutdown()   # 可重复调用：closer 与 atexit 都会调
        check("重复 shutdown 不抛异常", True)


def main() -> int:
    test_accesslog_unit()
    test_accesslog_http()
    test_metrics_labels()
    test_otel_drop_metric()
    test_cost_flush_on_shutdown()
    test_guards_shutdown()
    if FAILED:
        print(f"\nOBSERVABILITY TESTS FAILED：{len(FAILED)} 项")
        return 1
    print("\nOBSERVABILITY TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
