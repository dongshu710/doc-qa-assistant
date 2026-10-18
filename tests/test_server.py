"""Web 服务冒烟测试：起一个临时端口，验证 /api/health 与 /api/ask。

用法：python tests/test_server.py
（默认走 glm 测试通道；设 SENSENOVA_API_KEY 则为真实 LLM，否则离线抽取。）
"""
import json
import os
import sys
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("LLM_CHANNEL", "glm")

from src.server import create_server  # noqa: E402

httpd, pipe = create_server("127.0.0.1", 0, str(ROOT / "data" / "knowledge"))
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()

try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=10) as resp:
        health = json.loads(resp.read().decode("utf-8"))
    print("health:", health)

    for page, needle in (("/", "用有出处的答案"), ("/ask", "评测看板"), ("/dashboard", "评测看板"),
                         ("/report", "它不是什么"), ("/report", "链路与闸门")):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{page}", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        assert needle in html, page
    print("pages OK")

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/l3", timeout=10) as resp:
        l3 = json.loads(resp.read().decode("utf-8"))
    print("l3 available:", l3.get("available"), "| avg:", (l3.get("avg") or {}).get("faithfulness"))

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/report/export", timeout=20) as resp:
        disp = resp.headers.get("Content-Disposition", "")
        exported = resp.read().decode("utf-8")
    assert "attachment" in disp and "<!doctype html>" in exported.lower()
    print("export:", disp, "|", len(exported), "chars")

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/ask",
        data=json.dumps({"query": "稳盈系列的起购金额是多少"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    print("ask:", {k: data.get(k) for k in ("channel", "model", "behavior", "mode", "degraded", "latency_ms")})
    print("answer:", data["answer"])

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/metrics", timeout=10) as resp:
        metrics = json.loads(resp.read().decode("utf-8"))
    print("metrics.requests:", metrics.get("requests"))

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/knowledge", timeout=10) as resp:
        kb = json.loads(resp.read().decode("utf-8"))
    print("knowledge:", kb["total_chunks"], "chunks /", len(kb["files"]), "files")

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/trace?limit=5", timeout=10) as resp:
        trace = json.loads(resp.read().decode("utf-8"))
    print("trace items:", len(trace["items"]))

    reload_req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/reload",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(reload_req, timeout=10) as resp:
        rl = json.loads(resp.read().decode("utf-8"))
    print("reload:", rl)
    assert rl.get("ok") is True

    fb_req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/feedback",
        data=json.dumps({"trace_id": data.get("trace_id"), "useful": False, "comment": "smoke test"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(fb_req, timeout=10) as resp:
        fb = json.loads(resp.read().decode("utf-8"))
    print("feedback:", fb)

    assert health["status"] == "ok"
    assert health["channel"] == "glm"
    assert data["behavior"] == "answer" and data["answer"]
    assert fb.get("ok") is True
    print("SMOKE OK")
finally:
    httpd.shutdown()
