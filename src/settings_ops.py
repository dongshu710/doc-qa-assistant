"""设置面板的后台动作：探测模型、数/搬笔记、生成 MCP 配置。

为什么单独抽出来：这几个都是纯函数，原来留在 `create_server()` 的闭包里，
只能起真实服务打 HTTP 才测得到。搬到模块里可以单测，`server.py` 也少 80 行。

个人单机使用的前提：这些函数不假设对面是可信还是不可信的服务，
`base_url` 允许 localhost / 私网（本地 ollama、vLLM 就是这么用的），
只校验协议形态——安全边界由「只在本机跑」这件事本身提供。
"""
from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

PROBE_TIMEOUT_S = 15


def probe_llm(base_url: str, model: str, api_key: str, timeout_s: float = PROBE_TIMEOUT_S) -> dict:
    """真打一次最小请求验证配置。

    用户点「测试」要的是结论，不是重试次数，所以只打一次：
    重试会让等待翻倍，而 401/404 这类错误重试也不会变对。
    """
    base = str(base_url or "").rstrip("/")
    model = str(model or "")
    key = str(api_key or "")
    if not key:
        return {"ok": False, "error": "no_key", "message": "还没填密钥"}
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(base + "/chat/completions", data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            resp.read()
        return {"ok": True, "latency_ms": int((time.time() - started) * 1000)}
    except urllib.error.HTTPError as exc:
        hint = {401: "密钥无效或没有权限", 403: "密钥无权访问该模型",
                404: "地址不对：应填到 /v1 这一层，不要带 /chat/completions",
                429: "触发限流，稍后再试或换 Key"}.get(exc.code, "接口返回错误")
        return {"ok": False, "error": f"http_{exc.code}", "message": f"{hint}（HTTP {exc.code}）"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return {"ok": False, "error": "network",
                "message": f"连不上 {base}：{reason}（超时 {int(timeout_s)} 秒）"}


def count_notes(home: str) -> int:
    root = Path(home) / "notes"
    if not home or not root.is_dir():
        return 0
    return sum(1 for _ in root.rglob("*.md"))


def copy_notes(src: str, dst: str) -> dict:
    """把旧位置的笔记复到新位置。

    同名一律跳过：新位置可能已经有用户改过的同一篇，覆盖等于静默丢改动。
    只搬 notes/，索引会自动重建——搬索引反而容易带进过期缓存。
    """
    src_root = Path(src).expanduser().resolve() / "notes"
    dst_root = Path(dst).expanduser().resolve() / "notes"
    copied = skipped = 0
    failed: list[str] = []
    for path in src_root.rglob("*.md"):
        rel = path.relative_to(src_root)
        target = dst_root / rel
        if target.exists():
            skipped += 1
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += 1
        except OSError as exc:
            if len(failed) < 5:
                failed.append(f"{rel}: {exc}")
    return {"copied": copied, "skipped": skipped, "failed": failed}


def mcp_config(python: str, project_root: str, notes_home: str) -> dict:
    """生成 MCP 客户端配置：命令用绝对路径，不依赖对方的 PATH。"""
    return {
        "mcpServers": {
            "agent-notes": {
                "command": python,
                "args": ["-m", "src.notes.mcp_server"],
                "env": {"PYTHONPATH": project_root, "NOTE_HOME": notes_home},
            }
        }
    }
