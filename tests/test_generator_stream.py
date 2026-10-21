"""生成层流式：上游 SSE 解析、用量回传、截断检测与降级替换。"""
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline import RAGPipeline  # noqa: E402


class FakeUpstream(BaseHTTPRequestHandler):
    mode = "ok"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length or 0)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def send(obj) -> None:
            raw = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
            self.wfile.write(f"data: {raw}\n\n".encode("utf-8"))
            self.wfile.flush()

        send({"choices": [{"delta": {"content": "根据资料，"}}]})
        if FakeUpstream.mode == "truncate":
            return  # 没有 [DONE]，模拟连接被掐断
        send({"choices": [{"delta": {"content": "起购金额为 1 元。[1]"}}]})
        send({"choices": [{"delta": {}, "finish_reason": "stop"}],
              "usage": {"total_tokens": 12}})
        send("[DONE]")

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="gstream_")
    kb = Path(tmp) / "kb"
    kb.mkdir()
    (kb / "a.md").write_text("# 产品要素\n\n## 一、起购\n\n起购金额为 1 元。\n", encoding="utf-8")

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
    port = upstream.server_address[1]
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    env = {
        "LLM_API_KEY": "test-key", "DEEPSEEK_API_KEY": "",
        "LLM_BASE_URL": f"http://127.0.0.1:{port}/v1", "LLM_MODEL": "fake",
        "RETRIEVAL": "bm25", "MIN_SCORE": "0", "QUERY_EXPANSION": "off",
        "KEYWORD_MODE": "off", "KB_STORE": "off",
        "KEYWORD_INDEX": os.path.join(tmp, "kw.json"),
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        pipe = RAGPipeline(str(kb))
        events = list(pipe.ask_stream("起购金额是多少"))
        names = [n for n, _ in events]
        text = "".join(d for n, d in events if n == "delta")
        final = events[-1][1]
        assert names[-1] == "final" and "delta" in names, names
        assert text == "根据资料，起购金额为 1 元。[1]", text
        assert final["mode"] == "llm" and final["api_called"] is True, final
        assert (final.get("usage") or {}).get("total_tokens") == 12, final.get("usage")
        assert final["citations"][0]["ref"] == 1, final["citations"]
        print("stream ok:", text, "| usage:", final["usage"])

        FakeUpstream.mode = "truncate"
        events = list(pipe.ask_stream("起购金额是多少"))
        names = [n for n, _ in events]
        final = events[-1][1]
        assert "replace" in names, names
        assert final["mode"] == "extractive_fallback" and final["degraded"] is True, final
        assert "起购金额为 1 元" in final["answer"], final["answer"]
        print("truncate fallback ok:", final["degrade_reason"])
        print("GENERATOR STREAM TESTS PASSED")
    finally:
        upstream.shutdown()
        upstream.server_close()
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
