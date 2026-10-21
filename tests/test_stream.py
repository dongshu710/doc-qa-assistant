"""流式问答：SSE 事件顺序、final 完整性、多轮上下文与未命中路径。"""
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.split("\n\n"):
        name, data = "message", ""
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if data:
            events.append((name, json.loads(data)))
    return events


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="stream_")
    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(ROOT / "data" / "demo"),
        "KEYWORD_INDEX": os.path.join(tmp, "kw.json"),
        "RETRIEVAL": "bm25",
        "QUERY_EXPANSION": "off",
        "MIN_SCORE": "0",
        "KB_APPROVAL": "off",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY"):
        os.environ.pop(key, None)

    from src.server import create_server

    httpd, _pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def stream(payload):
        req = urllib.request.Request(
            base + "/api/ask/stream", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            assert resp.headers.get("Content-Type", "").startswith("text/event-stream"), resp.headers
            return parse_sse(resp.read().decode("utf-8"))

    try:
        # 1) 关键词路径：不生成，直接 final
        events = stream({"query": "我几点起床"})
        names = [name for name, _ in events]
        assert names == ["final"], names
        final = events[-1][1]
        assert final["path"] == "keyword" and final["api_called"] is False, final
        assert final["citations"][0]["doc_id"] and final["citations"][0]["chunk_index"] >= 0

        # 2) RAG 路径：先 delta，再 final；final 带完整引用
        events = stream({"query": "饮食方面有什么偏好", "session_id": "sess-stream"})
        names = [name for name, _ in events]
        assert "delta" in names and names[-1] == "final", names
        final = events[-1][1]
        assert final["turn"] == 1, final.get("turn")
        assert final["citations"] and final["citations"][0]["doc_id"], final
        assert final["answer"], final

        # 3) 多轮：追问带上上一轮
        events = stream({"query": "那作息呢", "session_id": "sess-stream"})
        final = events[-1][1]
        assert final["turn"] == 2, final.get("turn")
        assert final["context_query"] and "饮食" in final["context_query"], final.get("context_query")

        # 4) 未命中：只有 final，文案明确
        os.environ["MIN_SCORE"] = "0.99"
        httpd2, _ = create_server(HOST, 0)
        port2 = httpd2.server_address[1]
        threading.Thread(target=httpd2.serve_forever, daemon=True).start()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port2}/api/ask/stream",
            data=json.dumps({"query": "生活习惯有哪些"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            events = parse_sse(resp.read().decode("utf-8"))
        assert [n for n, _ in events] == ["final"], events
        assert events[0][1]["answer"] == "无法找到答案。", events[0][1]["answer"]
        httpd2.shutdown()
        httpd2.server_close()

        print("SSE events:", names)
        print("stream final:", final["answer"][:60])
        print("STREAM TESTS PASSED")
    finally:
        httpd.shutdown()
        httpd.server_close()
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
