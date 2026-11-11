"""知识库目录监听：外部改文件后自动重建索引。

为什么这条值得单独测：监听失败的表现是「改了没生效」，而用户会去怀疑检索不准——
两类完全不同的原因指向同一个症状，没有测试就只能靠猜。

测三件事：签名能识别变化、首次不触发、真起服务时改文件后问答跟着变。
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

from src.watcher import KnowledgeWatcher, dir_signature  # noqa: E402

FAILED = 0
HOST = "127.0.0.1"


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def test_signature() -> None:
    print("签名")
    tmp = Path(tempfile.mkdtemp(prefix="watch_"))
    (tmp / "a.md").write_text("内容一", encoding="utf-8")
    first = dir_signature(str(tmp))
    check("初次能读到文件", len(first) == 1, str(first))

    (tmp / "b.md").write_text("内容二", encoding="utf-8")
    second = dir_signature(str(tmp))
    check("新增文件改变签名", first != second, "签名没变")

    (tmp / "a.md").write_text("改过的内容，长度不同", encoding="utf-8")
    third = dir_signature(str(tmp))
    check("改内容改变签名（mtime 或 size 变）", second != third, "签名没变")

    check("目录不存在返回空元组（不抛错）",
          dir_signature(str(tmp / "不存在")) == (), "应该返回空")


def test_poll_logic() -> None:
    print("轮询判定")
    tmp = Path(tempfile.mkdtemp(prefix="watch2_"))
    (tmp / "a.md").write_text("初始", encoding="utf-8")
    calls = []
    watcher = KnowledgeWatcher(lambda: str(tmp), lambda: calls.append(1), interval=2)
    check("首次只记基线，不触发重建", watcher.poll_once() is False and not calls, str(calls))
    check("没有变化时不触发", watcher.poll_once() is False and not calls, str(calls))

    time.sleep(0.01)
    (tmp / "a.md").write_text("变了", encoding="utf-8")
    check("有变化时触发一次", watcher.poll_once() is True and len(calls) == 1, str(calls))
    check("同一次变化只触发一次（签名已更新）",
          watcher.poll_once() is False and len(calls) == 1, str(calls))
    check("重建计数正确", watcher.reloads == 1, str(watcher.reloads))

    boom = KnowledgeWatcher(lambda: str(tmp), lambda: (_ for _ in ()).throw(RuntimeError("重建炸了")),
                            interval=2)
    boom.poll_once()
    (tmp / "c.md").write_text("再变", encoding="utf-8")
    check("重建抛错被吞住并记录（线程不能死）",
          boom.poll_once() is False and "重建炸了" in boom.last_error, boom.last_error)

    check("间隔有下限（防止配置成 0.1 秒空转）",
          KnowledgeWatcher(lambda: str(tmp), lambda: None, interval=0.1).interval >= 2.0,
          str(KnowledgeWatcher(lambda: str(tmp), lambda: None, interval=0.1).interval))


def test_end_to_end() -> None:
    print("HTTP：改文件后问答跟着变")
    tmp = tempfile.mkdtemp(prefix="watch_e2e_")
    seed = Path(tmp) / "seed"
    seed.mkdir(parents=True)
    (seed / "产品.md").write_text(
        "# 产品\n\n## 要素\n第1条 稳盈系列产品的起购金额为 1 元。\n", encoding="utf-8")
    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(seed),
        "KEYWORD_INDEX": os.path.join(tmp, "kw.json"),
        "RETRIEVAL": "bm25",
        "QUERY_EXPANSION": "off",
        "MIN_SCORE": "0",
        "KB_APPROVAL": "off",
        "KB_WATCH_SECONDS": "2",     # 测试里用下限，别等 5 秒
    }
    old = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY", "API_KEYS"):
        os.environ.pop(key, None)

    from src.server import create_server

    httpd, pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def health() -> dict:
        with urllib.request.urlopen(base + "/api/health", timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    data = health()
    check("健康检查里能看到监听在跑", data.get("kb_watch", {}).get("enabled") is True,
          str(data.get("kb_watch")))

    def ask(query: str) -> dict:
        req = urllib.request.Request(
            base + "/api/ask", data=json.dumps({"query": query}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    before = ask("稳盈系列产品的起购金额是多少")
    check("初次能答出 1 元", "1 元" in (before.get("answer") or ""),
          (before.get("answer") or "")[:80])

    # 直接改活动版本目录里的文件：模拟「用编辑器改条款」
    active = pipe.knowledge_dir
    target = None
    for name in os.listdir(active):
        if name.endswith(".md"):
            target = os.path.join(active, name)
            break
    check("找到要改的文件", target is not None, active)
    Path(target).write_text(
        "# 产品\n\n## 要素\n第1条 稳盈系列产品的起购金额为 5 元。\n", encoding="utf-8")

    deadline = time.monotonic() + 30
    reloads = 0
    while time.monotonic() < deadline:
        info = health().get("kb_watch") or {}
        reloads = int(info.get("reloads") or 0)
        if reloads >= 1 and not (health().get("index") or {}).get("rebuilding"):
            break
        time.sleep(1)
    check("监听触发了重建", reloads >= 1, str(reloads))

    # 重建可能刚结束，给索引一点点稳定时间再问
    for _ in range(10):
        after = ask("稳盈系列产品的起购金额是多少")
        if "5 元" in (after.get("answer") or ""):
            break
        time.sleep(1)
    check("改完不重启，答案变成 5 元", "5 元" in (after.get("answer") or ""),
          (after.get("answer") or "")[:100])

    httpd.shutdown()
    httpd.server_close()
    check("停机后线程被收掉（不留后台线程）", not any(
        t.name == "kb-watch" and t.is_alive() for t in threading.enumerate()),
        str([t.name for t in threading.enumerate()]))

    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_disabled() -> None:
    print("关闭时的状态字段")
    tmp = tempfile.mkdtemp(prefix="watch_off_")
    seed = Path(tmp) / "seed"
    seed.mkdir(parents=True)
    (seed / "a.md").write_text("# 标题\n\n正文内容足够长，用于初始化知识库。\n", encoding="utf-8")
    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(seed),
        "KEYWORD_INDEX": os.path.join(tmp, "kw.json"),
        "RETRIEVAL": "bm25",
        "KB_APPROVAL": "off",
        "KB_WATCH_SECONDS": "0",
    }
    old = {key: os.environ.get(key) for key in env}
    os.environ.update(env)

    from src.server import create_server

    httpd, _pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    check("关闭时回 enabled=false 而不是缺字段",
          data.get("kb_watch") == {"enabled": False}, str(data.get("kb_watch")))
    httpd.shutdown()
    httpd.server_close()
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def main() -> None:
    test_signature()
    test_poll_logic()
    test_end_to_end()
    test_disabled()
    if FAILED:
        print(f"\nWATCHER: {FAILED} FAILED")
        raise SystemExit(1)
    print("\nWATCHER OK")


if __name__ == "__main__":
    main()
