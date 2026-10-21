"""Web 服务冒烟测试：起一个临时端口，验证 /api/health 与 /api/ask。

用法：python tests/test_server.py
（未配置 LLM_API_KEY 时自动走离线抽取，配置后为真实模型。）
"""
import json
import sys
import threading
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.server import create_server  # noqa: E402

httpd, pipe = create_server("127.0.0.1", 0, str(ROOT / "data" / "knowledge"))
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()

try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=10) as resp:
        health = json.loads(resp.read().decode("utf-8"))
    print("health:", health)
    assert health.get("retrieval") == "vector"
    assert health.get("guards", {}).get("budget", {}).get("limit", 0) > 0

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/examples?n=4", timeout=10) as resp:
        examples = json.loads(resp.read().decode("utf-8"))["items"]
    assert len(examples) >= 1
    print("examples:", examples)

    for page, needle in (("/", "有出处的答案"), ("/ask", "可以这样问"), ("/kb", "拖拽或点击上传"),
                         ("/dashboard", "评测看板"),
                         ("/report", "工程能力"), ("/report", "链路与闸门")):
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
        headers={"Content-Type": "application/json", "Idempotency-Key": "smoke-ask"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    print("ask:", {k: data.get(k) for k in ("channel", "model", "behavior", "mode", "degraded", "latency_ms")})
    print("answer:", data["answer"])

    # 引用必须能回原文：doc_id/chunk_index 齐全，/api/source 能取到同一块
    cite = data["citations"][0]
    assert cite.get("doc_id") and cite.get("chunk_index") is not None, cite
    assert "kb_version" in data, "响应应带版本字段（未启用版本库时为 None）"
    src_url = (f"http://127.0.0.1:{port}/api/source?doc="
               + urllib.parse.quote(str(cite["doc_id"]))
               + f"&chunk={cite['chunk_index']}")
    with urllib.request.urlopen(src_url, timeout=10) as resp:
        src = json.loads(resp.read().decode("utf-8"))
    assert src["doc_id"] == cite["doc_id"] and src["text"].strip(), src
    assert src.get("version") == data.get("kb_version"), src
    print("source:", src["title"], "·", src["section"], "|", len(src["text"]), "chars")
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/source?doc=x&chunk=99999", timeout=10)
        raise AssertionError("越界 chunk 应 404")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404

    with urllib.request.urlopen(req, timeout=90) as resp:
        replay = json.loads(resp.read().decode("utf-8"))
        replay_header = resp.headers.get("X-Idempotent-Replay")
    assert replay["trace_id"] == data["trace_id"] and replay_header == "true"
    print("idempotency: replay OK")

    miss_req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/ask",
        data=json.dumps({"query": "今天天气怎么样"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(miss_req, timeout=30) as resp:
        miss = json.loads(resp.read().decode("utf-8"))
    assert miss["behavior"] == "no_answer"
    assert miss["answer"] == "无法找到答案。"
    assert miss.get("similar_questions")
    print("no-answer:", miss["answer"], "| similar:", len(miss["similar_questions"]))

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/admin/config", timeout=10) as resp:
        admin = json.loads(resp.read().decode("utf-8"))
    assert admin.get("ok") is True and "runtime" in admin
    print("admin config:", admin["runtime"])

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
    assert health["channel"], "health 应返回端点标识"
    assert data["behavior"] == "answer" and data["answer"]
    assert fb.get("ok") is True
    print("SMOKE OK")
finally:
    httpd.shutdown()
