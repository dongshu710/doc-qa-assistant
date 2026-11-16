"""非流式调用的总墙钟：上游「每几秒吐一个字节」必须被掐断。

为什么要这条：`urlopen(timeout=)` 只管 socket 空闲超时。上游只要每 29 秒发一个
字节，一次调用就能把请求线程占几十分钟，而 `generate()` 的墙钟预算在重试循环
外面，看不到单次调用内部的进展。现在 `chat()` 走流式累积并共用
`LLM_STREAM_MAX_S` 总预算，到点必抛。

两个假上游：
- 慢滴：每 0.2 秒吐一小段，永远不发 [DONE]；
- 老式：完全不认 `stream=true`，直接回一整段 JSON（验证降级路径没坏）。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILED = 0
MODE = {"value": "slow"}


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


class FakeUpstream(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length or 0)
        if MODE["value"] == "json":
            body = json.dumps({"choices": [{"message": {"content": "老式接口的回答"}}],
                               "usage": {"total_tokens": 7}}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for _ in range(1000):
                chunk = {"choices": [{"delta": {"content": "字"}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.2)          # 慢滴：单次读写都不算「空闲超时」
        except OSError:
            # 被我们掐断是预期结果。Windows 上表现为 ConnectionAbortedError
            # （WinError 10053），不是 BrokenPipe，所以这里按 OSError 兜。
            pass

    def log_message(self, *args) -> None:
        pass


def main() -> int:
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
    port = upstream.server_address[1]
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    env = {
        "LLM_API_KEY": "test-key", "DEEPSEEK_API_KEY": "",
        "LLM_BASE_URL": f"http://127.0.0.1:{port}/v1", "LLM_MODEL": "fake",
        # 1.2 秒总预算：慢滴上游会想发 200 秒
        "LLM_STREAM_MAX_S": "1.2",
        "LLM_TIMEOUT_S": "60",            # 故意给大：证明掐断不是靠 socket 超时
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        from src import generator

        began = time.monotonic()
        raised = None
        try:
            generator.chat([{"role": "user", "content": "你好"}])
        except Exception as exc:  # noqa: BLE001 —— 这里就是要它抛
            raised = exc
        elapsed = time.monotonic() - began
        check("慢滴上游被总墙钟掐断", raised is not None, "居然正常返回了")
        check("掐断发生在预算附近而不是 60 秒后", elapsed < 8.0, f"{elapsed:.1f}s")
        print(f"       实际耗时 {elapsed:.1f}s，异常：{type(raised).__name__}: {raised}"[:160])

        # 上游不认 stream=true：降级回一次阻塞调用，行为与老版本一致
        MODE["value"] = "json"
        began = time.monotonic()
        text, usage = generator.chat([{"role": "user", "content": "你好"}])
        check("不支持流式的上游能降级成功", text == "老式接口的回答", text[:80])
        check("降级路径带回用量", (usage or {}).get("total_tokens") == 7, str(usage))
        print(f"       降级耗时 {time.monotonic() - began:.2f}s")
    finally:
        upstream.shutdown()
        upstream.server_close()
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("LLM WALLCLOCK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
