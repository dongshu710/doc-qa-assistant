"""设置面板纯逻辑的单元测试：模型探测、笔记计数与迁移、MCP 配置。

跑法：python tests/test_settings_ops.py

为什么单独写：这几个函数原来埋在 create_server 的闭包里，只能起真实服务才测得到；
抽到 settings_ops 之后可以在进程内验证错误分类，不必依赖外网，也不必等超时。
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import settings_ops  # noqa: E402

failures: list[str] = []
passed = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed
    if cond:
        passed += 1
        print(f"  ok   {name}")
    else:
        failures.append(name)
        print(f"  FAIL {name} {extra}")


class FakeLLM(BaseHTTPRequestHandler):
    """按路径返回预设状态码，用来验证 probe_llm 的错误分类。"""

    status = 200
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length:
            self.rfile.read(length)
        body = b'{"ok":true}' if FakeLLM.status == 200 else b'{"error":"x"}'
        self.send_response(FakeLLM.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def start_fake(status: int) -> tuple[ThreadingHTTPServer, str]:
    FakeLLM.status = status
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeLLM)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/v1"


def main() -> int:
    print("probe_llm")
    check("没填密钥直接拒绝", settings_ops.probe_llm("http://127.0.0.1:1/v1", "m", "")["error"] == "no_key")

    httpd, base = start_fake(200)
    try:
        ok = settings_ops.probe_llm(base, "demo", "sk-x")
        check("200 视为可用", ok["ok"] is True)
        check("返回往返耗时", isinstance(ok.get("latency_ms"), int))
    finally:
        httpd.shutdown()

    httpd, base = start_fake(401)
    try:
        bad = settings_ops.probe_llm(base, "demo", "sk-x")
        check("401 判为密钥问题", bad["error"] == "http_401")
        check("401 提示可读", "密钥" in bad["message"], bad["message"])
    finally:
        httpd.shutdown()

    httpd, base = start_fake(404)
    try:
        miss = settings_ops.probe_llm(base, "demo", "sk-x")
        check("404 提示地址层级", "地址不对" in miss["message"], miss["message"])
    finally:
        httpd.shutdown()

    dead = settings_ops.probe_llm("http://127.0.0.1:9/v1", "demo", "sk-x", timeout_s=2)
    check("连不上归为网络错误", dead["error"] == "network", str(dead))

    print("count_notes / copy_notes")
    tmp = Path(tempfile.mkdtemp(prefix="ops-"))
    empty = tmp / "empty"
    empty.mkdir()
    check("没有 notes 目录算 0 篇", settings_ops.count_notes(str(empty)) == 0)

    old = tmp / "old"
    (old / "notes" / "2026" / "10").mkdir(parents=True)
    for idx in range(3):
        (old / "notes" / "2026" / "10" / f"n{idx}.md").write_text(f"# 第 {idx} 篇\n", encoding="utf-8")
    check("数得准", settings_ops.count_notes(str(old)) == 3)

    new = tmp / "new"
    (new / "notes" / "2026" / "10").mkdir(parents=True)
    (new / "notes" / "2026" / "10" / "n1.md").write_text("# 用户改过的\n", encoding="utf-8")
    result = settings_ops.copy_notes(str(old), str(new))
    check("复制了两篇", result["copied"] == 2, str(result))
    check("同名跳过一篇", result["skipped"] == 1, str(result))
    kept = (new / "notes" / "2026" / "10" / "n1.md").read_text(encoding="utf-8")
    check("同名文件没被覆盖", "用户改过的" in kept, kept)
    check("迁移后旧目录仍在", (old / "notes" / "2026" / "10" / "n0.md").exists())
    check("新位置总数正确", settings_ops.count_notes(str(new)) == 3)

    print("mcp_config")
    cfg = settings_ops.mcp_config("C:/py/python.exe", "D:/proj", "D:/notes")
    server = cfg["mcpServers"]["agent-notes"]
    check("命令是绝对路径", server["command"] == "C:/py/python.exe")
    check("用 -m 起模块", server["args"] == ["-m", "src.notes.mcp_server"])
    check("带 PYTHONPATH", server["env"]["PYTHONPATH"] == "D:/proj")
    check("带 NOTE_HOME", server["env"]["NOTE_HOME"] == "D:/notes")
    check("可被 JSON 序列化", bool(json.dumps(cfg)))

    print("mcp_targets：只认已知客户端，路径按平台推")
    win = settings_ops.mcp_targets(home="C:/Users/u", os_name="nt", appdata="C:/Users/u/AppData/Roaming")
    ids = [t["id"] for t in win]
    check("Windows 给出四个客户端", ids == ["claude", "cursor", "cline", "windsurf"], str(ids))
    by_id = {t["id"]: t for t in win}
    check("Claude 读 APPDATA",
          by_id["claude"]["path"].replace("\\", "/").endswith("AppData/Roaming/Claude/claude_desktop_config.json"),
          by_id["claude"]["path"])
    check("Cursor 在用户目录下 .cursor/mcp.json",
          by_id["cursor"]["path"].replace("\\", "/").endswith("/.cursor/mcp.json"),
          by_id["cursor"]["path"])
    check("Cline 走 VS Code globalStorage",
          "saoudrizwan.claude-dev" in by_id["cline"]["path"], by_id["cline"]["path"])
    check("路径都是字符串", all(isinstance(t["path"], str) and t["path"] for t in win))

    mac = settings_ops.mcp_targets(home="/Users/u", os_name="darwin")
    mac_claude = {t["id"]: t["path"] for t in mac}["claude"]
    check("macOS 用 Application Support",
          mac_claude.replace("\\", "/").endswith("Library/Application Support/Claude/claude_desktop_config.json"),
          mac_claude)

    linux = settings_ops.mcp_targets(home="/home/u", os_name="posix")
    linux_claude = {t["id"]: t["path"] for t in linux}["claude"]
    check("Linux 用 ~/.config", linux_claude.replace("\\", "/").endswith(".config/Claude/claude_desktop_config.json"),
          linux_claude)

    check("exists 字段是布尔", all(isinstance(t["exists"], bool) for t in win))
    # 绝不接受调用方传路径：函数签名里没有 path 参数
    import inspect
    params = list(inspect.signature(settings_ops.mcp_targets).parameters)
    check("签名里没有可注入的任意路径", "path" not in params, str(params))

    print(f"\n{passed} 项通过，{len(failures)} 项失败")
    if failures:
        print("失败项：" + "、".join(failures))
        return 1
    print("SETTINGS OPS OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
