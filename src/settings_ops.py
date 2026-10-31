"""设置面板的后台动作：探测模型、数/搬笔记、生成 MCP 配置。

为什么单独抽出来：这几个都是纯函数，原来留在 `create_server()` 的闭包里，
只能起真实服务打 HTTP 才测得到。搬到模块里可以单测，`server.py` 也少 80 行。

个人单机使用的前提：这些函数不假设对面是可信还是不可信的服务，
`base_url` 允许 localhost / 私网（本地 ollama、vLLM 就是这么用的），
只校验协议形态——安全边界由「只在本机跑」这件事本身提供。
"""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROBE_TIMEOUT_S = 15
_ALLOWED_SCHEMES = ("http", "https")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """探测不跟随重定向。

    跟随的话，填一个看似正常、实际 302 到 169.254.169.254 或内网地址的
    base_url，就能把「测试连接」当成内网探测跳板。测试连接只需要知道对面
    通不通，3xx 本身就说明地址填错了，直接在结果里说清即可。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


def _host_is_private(host: str) -> bool:
    """解析出的任一地址落在本机/内网/链路本地就视为私网。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


def _private_probe_allowed() -> bool:
    """默认允许私网：本地 ollama / vLLM 就是 127.0.0.1，一刀切会把它废掉。

    对外部署（配了 ALLOWED_HOSTS、不再只绑回环）时应设 PROBE_ALLOW_PRIVATE=0，
    否则「测试连接」就是个可用的内网探测器。
    """
    raw = (os.environ.get("PROBE_ALLOW_PRIVATE") or "1").strip().lower()
    return raw not in ("0", "off", "false", "no")


def probe_llm(base_url: str, model: str, api_key: str, timeout_s: float = PROBE_TIMEOUT_S) -> dict:
    """真打一次最小请求验证配置。

    用户点「测试」要的是结论，不是重试次数，所以只打一次：
    重试会让等待翻倍，而 401/404 这类错误重试也不会变对。

    这条路径的入参完全由调用方给，所以三件事必须自己做：协议白名单、
    不跟随重定向、可选封禁私网。少了任何一条，它就是个内网探测接口。
    """
    base = str(base_url or "").rstrip("/")
    model = str(model or "")
    key = str(api_key or "")
    if not key:
        return {"ok": False, "error": "no_key", "message": "还没填密钥"}
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        return {"ok": False, "error": "bad_url",
                "message": "地址要以 http:// 或 https:// 开头，并带上主机名"}
    if not _private_probe_allowed() and _host_is_private(parsed.hostname):
        return {"ok": False, "error": "private_host",
                "message": "PROBE_ALLOW_PRIVATE 已关闭，不允许探测本机或内网地址"}
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(base + "/chat/completions", data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    started = time.monotonic()
    try:
        with _NO_REDIRECT_OPENER.open(req, timeout=timeout_s) as resp:
            resp.read()
        return {"ok": True, "latency_ms": int((time.monotonic() - started) * 1000)}
    except urllib.error.HTTPError as exc:
        hint = {301: "地址发生了重定向，请直接填最终地址",
                302: "地址发生了重定向，请直接填最终地址",
                307: "地址发生了重定向，请直接填最终地址",
                308: "地址发生了重定向，请直接填最终地址",
                401: "密钥无效或没有权限", 403: "密钥无权访问该模型",
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
    return _walk(root, suffix=".md")["files"]


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


MCP_CLIENTS = {
    "claude": "Claude Desktop",
    "cursor": "Cursor",
    "cline": "Cline（VS Code 扩展）",
    "windsurf": "Windsurf",
}


def mcp_targets(home: str | os.PathLike | None = None, os_name: str | None = None,
                appdata: str | None = None) -> list[dict]:
    """各 MCP 客户端的配置文件位置；找不到的那个平台就不给。

    为什么只认已知客户端、不接受调用方传路径：这个接口会「写别人的配置文件」，
    一旦允许任意路径，就等于在本地服务里开了一个任意写文件的洞。
    参数只为可测试（注入 home / 平台 / APPDATA），生产调用一律用默认值。
    """
    home_path = Path(home) if home else Path.home()
    name = os_name if os_name is not None else os.name
    app_dir = Path(appdata) if appdata is not None else (
        Path(os.environ.get("APPDATA") or home_path) if os.environ.get("APPDATA") else None)

    def pick(*candidates: Path | None) -> Path | None:
        for item in candidates:
            if item is not None:
                return item
        return None

    if name == "nt":
        claude = pick(app_dir and app_dir / "Claude" / "claude_desktop_config.json")
        cline = pick(app_dir and app_dir / "Code" / "User" / "globalStorage"
                     / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json")
    elif name == "darwin":
        claude = home_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        cline = (home_path / "Library" / "Application Support" / "Code" / "User" / "globalStorage"
                 / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json")
    else:
        claude = home_path / ".config" / "Claude" / "claude_desktop_config.json"
        cline = (home_path / ".config" / "Code" / "User" / "globalStorage"
                 / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json")

    found = {
        "claude": claude,
        "cursor": home_path / ".cursor" / "mcp.json",
        "cline": cline,
        "windsurf": home_path / ".codeium" / "windsurf" / "mcp_config.json",
    }
    return [{"id": key, "name": MCP_CLIENTS[key], "path": str(found[key]),
             "exists": found[key].exists()}
            for key in MCP_CLIENTS if found.get(key) is not None]


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


# ---------- 存储占用 ----------
# 设置页要回答的是「我的东西有多大、还能放多少」，所以这里只数磁盘上的真实字节，
# 不去估算「每篇约多少 KB」——估出来的数字一旦和资源管理器对不上，用户就不信了。
#
# 性能上有两道处理，因为笔记上千篇时这里要遍历 4~5 个目录树：
# 1. `os.scandir` 而不是 `Path.rglob`：Windows 上目录项自带 size，省掉每条一次 stat，
#    而且 `Path` 对象创建本身在千级条目上就不便宜；
# 2. 结果按「路径 + 变更指纹」缓存 30 秒：打开设置是高频动作（每次点齿轮都算一遍），
#    但笔记内容不会在 30 秒内变几十次。指纹取索引文件与各根目录的 mtime/size，
#    存一篇笔记立刻变——所以缓存不会给出过期数字，只是不重复扫。

_STORAGE_TTL_S = 30.0
# key 是「统计哪几个目录」，value 是 (指纹, 时间戳, 报表)
_STORAGE_CACHE: dict = {}
_STORAGE_STATS = {"hits": 0, "misses": 0, "last_ms": 0.0}


def _walk(root: Path, suffix: str = "") -> dict:
    """遍历目录，返回 {bytes, files}。

    只走真实目录、只算普通文件：符号链接不跟（避免环）、权限不足的条目跳过
    （正在被删的临时文件不该把面板打成 500）。
    """
    total = 0
    files = 0
    stack = [str(root)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            if suffix and not entry.name.endswith(suffix):
                                continue
                            total += entry.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return {"bytes": total, "files": files}


def _size_of(root: Path) -> dict:
    """目录总字节与文件数。权限不足或正在被删的条目直接跳过，不让统计把面板打成 500。"""
    if not root.exists():
        return {"bytes": 0, "files": 0}
    if root.is_file():
        try:
            return {"bytes": root.stat().st_size, "files": 1}
        except OSError:
            return {"bytes": 0, "files": 0}
    return _walk(root)


def _stamp(*targets) -> tuple:
    """变更指纹：mtime + size 拼起来。一次 stat 几十微秒，比扫一遍目录便宜三个数量级。"""
    out = []
    for target in targets:
        try:
            stat = os.stat(str(target))
            out.append(f"{target}|{stat.st_mtime_ns}|{stat.st_size}")
        except OSError:
            out.append(f"{target}|-|-")
    return tuple(out)


def invalidate_storage() -> None:
    """显式作废缓存：清理/迁移这类「刚删完就要看结果」的动作用。"""
    _STORAGE_CACHE.clear()


def _clone(report: dict) -> dict:
    """返回前把每层 dict 都复制一遍：调用方往里塞字段不该改到缓存里的那份。"""
    return {key: (dict(value) if isinstance(value, dict) else value)
            for key, value in report.items()}


def storage_stats() -> dict:
    """命中的计数，给测试和排查用（页面不展示）。"""
    return dict(_STORAGE_STATS, cached=len(_STORAGE_CACHE))



def _disk_of(target: Path) -> dict:
    probe = target
    # 目录可能还没建（自定义位置刚填），往上找到第一个存在的祖先再问磁盘
    for _ in range(8):
        try:
            usage = shutil.disk_usage(str(probe))
            break
        except OSError:
            if probe.parent == probe:
                return {"total": 0, "free": 0, "root": ""}
            probe = probe.parent
    else:
        return {"total": 0, "free": 0, "root": ""}
    return {"total": usage.total, "free": usage.free, "root": str(probe)}


def storage_report(notes_home: str, kb_root: str, index_dir: str,
                   config_path: str, keep_versions: int, fresh: bool = False) -> dict:
    """一次统计：笔记 / 索引 / 知识库 / 配置 / 向量索引各自的真实占用。

    `fresh=True` 跳过缓存（清理前后要拿准数，不能拿 30 秒前的）。
    """
    home = Path(notes_home).expanduser() if notes_home else Path.home() / "agent-notes"
    kb = Path(kb_root) if kb_root else None
    key = (str(home), kb_root or "", index_dir or "", config_path or "", int(keep_versions or 0))
    stamp = _stamp(
        home / "notes",
        home / "index" / "notes.jsonl",
        kb or home / "-",
        (kb / "versions") if kb else home / "-",
        config_path or home / "-",
        home / "threads",
        home / "assets",
    )
    now = time.monotonic()
    hit = _STORAGE_CACHE.get(key)
    if not fresh and hit and hit[0] == stamp and now - hit[1] < _STORAGE_TTL_S:
        _STORAGE_STATS["hits"] += 1
        report = _clone(hit[2])
        report["cached"] = True
        report["took_ms"] = 0
        return report

    _STORAGE_STATS["misses"] += 1
    started = time.perf_counter()

    # 五个根目录互不相干，并行扫：Windows 上单次 stat 被杀毒软件拖到 8~9 ms 级，
    # 串行扫四个树就是把等待时间加起来。
    targets = {"notes": home / "notes", "threads": home / "threads", "index": home / "index",
               "assets": home / "assets"}
    if kb:
        targets["kb"] = kb
    if config_path:
        targets["config"] = Path(config_path)
    if index_dir:
        targets["embedding"] = Path(index_dir)
    results: dict = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {name: pool.submit(_size_of, path) for name, path in targets.items()}
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except Exception:  # 统计失败不该让整块面板 500
                results[name] = {"bytes": 0, "files": 0}

    versions = 0
    if kb:
        try:
            versions = sum(1 for name in os.listdir(kb / "versions") if name.startswith("v"))
        except OSError:
            versions = 0

    report = {
        "notes": {**results.get("notes", {"bytes": 0, "files": 0}), "path": str(home / "notes")},
        "threads": {**results.get("threads", {"bytes": 0, "files": 0}), "path": str(home / "threads")},
        "index": {**results.get("index", {"bytes": 0, "files": 0}), "path": str(home / "index")},
        "assets": {**results.get("assets", {"bytes": 0, "files": 0}), "path": str(home / "assets")},
        "kb": {**results.get("kb", {"bytes": 0, "files": 0}), "path": str(kb_root or ""),
               "versions": versions},
        "config": {**results.get("config", {"bytes": 0, "files": 0}), "path": str(config_path or "")},
        "embedding": results.get("embedding", {"bytes": 0, "files": 0}),
        "disk": _disk_of(home),
        "keep_versions": int(keep_versions or 0),
        "cached": False,
        "took_ms": int((time.perf_counter() - started) * 1000),
    }
    _STORAGE_CACHE[key] = (stamp, now, report)
    return _clone(report)



def clear_index(home: str) -> int:
    """删掉笔记索引缓存，返回释放的字节数。

    索引只是缓存（`notes.jsonl`），删掉会在下次读取时重建；
    这也是面板上唯一一个「删了不会丢数据」的按钮，所以文案必须说清是缓存。
    """
    target = Path(home).expanduser() / "index"
    freed = _size_of(target)["bytes"]
    shutil.rmtree(target, ignore_errors=True)
    return freed

