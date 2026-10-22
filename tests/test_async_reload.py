"""后台重建 + 增量解析：上传立即返回、旧索引继续服务、只重解析变更文档。

为什么必须测「重建中仍可问答」：异步化最容易引入的回归是把旧索引提前清空，
表现为上传后几十毫秒内所有问题都「无法找到答案」。
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOST = "127.0.0.1"
_KEYS = ("LLM_API_KEY", "DEEPSEEK_API_KEY")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _post(port: int, path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"http://{HOST}:{port}{path}", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(port: int, path: str) -> dict:
    with urllib.request.urlopen(f"http://{HOST}:{port}{path}", timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="async_reload_"))
    seed = tmp / "seed"
    seed.mkdir()
    for i in range(3):
        _write(seed / f"doc{i}.md", f"# 文档{i}\n\n## 要素\n\n文档{i}的起购金额是 {1000 + i} 元。\n")

    env = {
        "KB_DIR": str(tmp / "kb"), "KB_SEED_DIR": str(seed),
        "KEYWORD_INDEX": str(tmp / "keywords.json"),
        "RETRIEVAL": "bm25", "QUERY_EXPANSION": "off",
        "KB_APPROVAL": "off", "KB_ASYNC_RELOAD": "on",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    for key in _KEYS:
        os.environ.pop(key, None)

    from src.server import create_server

    httpd, pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    # 人为放慢构建，制造「正在重建」的窗口；否则本机建 4 个块只要几毫秒，测不到竞态
    original_build = pipe._build_index

    def slow_build(target):
        time.sleep(0.35)
        return original_build(target)

    pipe._build_index = slow_build

    try:
        before = _get(port, "/api/health")["index"]
        assert before["rebuilding"] is False, before
        base_chunks = before["chunks_now"]
        print(f"初始索引 OK：{base_chunks} 块，builds={before['builds']}")

        # ---------- 1) 上传立即返回，索引在后台建 ----------
        started = time.time()
        up = _post(port, "/api/knowledge/upload", {
            "name": "新增产品.md",
            "content": "# 新增产品\n\n## 要素\n\n新增产品的起购金额是 5000 元。\n",
        })
        elapsed_ms = (time.time() - started) * 1000
        assert up["ok"] and up["rebuilding"] is True, up
        assert up["chunks"] is None, up
        assert elapsed_ms < 300, f"上传被重建阻塞：{elapsed_ms:.0f}ms"
        print(f"上传立即返回 OK：{elapsed_ms:.0f}ms，rebuilding=true")

        # ---------- 2) 重建期间旧索引仍可问答 ----------
        mid = _get(port, "/api/health")["index"]
        assert mid["rebuilding"] is True, mid
        ask = _post(port, "/api/ask", {"query": "文档1的起购金额"})
        assert ask.get("behavior") in ("answer", "no_answer"), ask
        assert ask.get("answer"), ask
        print(f"重建中问答 OK：behavior={ask['behavior']}")

        # ---------- 3) 完成后切换，且只解析新增文档 ----------
        deadline = time.time() + 20
        state = mid
        while time.time() < deadline:
            state = _get(port, "/api/health")["index"]
            if not state["rebuilding"]:
                break
            time.sleep(0.05)
        assert state["rebuilding"] is False, state
        assert state["last_error"] is None, state
        assert state["chunks_now"] > base_chunks, (base_chunks, state)
        assert state["parsed_docs"] == 1, state
        assert state["reused_docs"] == 3, state
        print(f"后台重建完成 OK：+{state['chunks_now'] - base_chunks} 块，"
              f"解析 {state['parsed_docs']} / 复用 {state['reused_docs']}，"
              f"{state['last_ms']}ms")

        # ---------- 4) 硬链接保留 mtime，改动一份只重解析一份 ----------
        up2 = _post(port, "/api/knowledge/upload", {
            "name": "doc1.md",
            "content": "# 文档1\n\n## 要素\n\n文档1的起购金额调整为 2000 元。\n",
        })
        assert up2["ok"], up2
        deadline = time.time() + 20
        while time.time() < deadline:
            state = _get(port, "/api/health")["index"]
            if not state["rebuilding"]:
                break
            time.sleep(0.05)
        assert state["parsed_docs"] == 1, state
        assert state["reused_docs"] == 3, state
        print(f"增量解析 OK：解析 {state['parsed_docs']} / 复用 {state['reused_docs']}")

        answer = _post(port, "/api/ask", {"query": "文档1的起购金额"})
        assert "2000" in (answer.get("answer") or ""), answer.get("answer")
        print("新内容已可检索 OK：命中 2000 元")

        # ---------- 5) 连续触发合并为一轮 pending ----------
        builds_before = state["builds"]
        _post(port, "/api/reload", {})
        _post(port, "/api/reload", {})
        deadline = time.time() + 20
        while time.time() < deadline:
            state = _get(port, "/api/health")["index"]
            if not state["rebuilding"] and not state["pending"]:
                break
            time.sleep(0.05)
        assert state["builds"] - builds_before <= 2, state
        assert state["last_error"] is None, state
        print(f"重复触发合并 OK：builds +{state['builds'] - builds_before}")

        print("ASYNC RELOAD TESTS PASSED")
    finally:
        httpd.shutdown()
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    main()
