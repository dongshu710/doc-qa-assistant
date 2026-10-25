#!/usr/bin/env python3
"""知源文件 · 命令行入口（零第三方依赖）。

为什么要有这层脚本：技能里写「先 curl 再 jq 再自己拼 front matter」等于每次让模型重写一遍，
而且 Windows 下没有 jq。这里把读、搜、存、导出、打开收敛成几个固定命令，模型只需要选命令。

读走本地文件（服务没起也能看），写走 HTTP（服务负责切分与摘要），
两条路都失败时明确报错并给下一步，不静默降级。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = SKILL_DIR / "config.json"
DEFAULT_BASE = "http://127.0.0.1:8000"
TIMEOUT = 6.0
FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)


# ---------------------------------------------------------------- 配置

def load_config() -> dict:
    """config.json 不存在不算错：默认值就够用，少一个必填项就少一类安装失败。"""
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def setting(args, attr: str, env: str, key: str, default: str = "") -> str:
    """优先级：命令行 > 环境变量 > config.json > 默认值。"""
    value = getattr(args, attr, None)
    if value:
        return str(value)
    env_value = os.environ.get(env, "").strip()
    if env_value:
        return env_value
    cfg_value = str(load_config().get(key, "") or "").strip()
    return cfg_value or default


def base_url(args) -> str:
    return setting(args, "base_url", "ZHIYUAN_BASE_URL", "base_url", DEFAULT_BASE).rstrip("/")


def note_home(args) -> Path:
    raw = setting(args, "home", "NOTE_HOME", "note_home", str(Path.home() / "agent-notes"))
    return Path(raw).expanduser()


def zhiyuan_home(args) -> Path | None:
    raw = setting(args, "zhiyuan_home", "ZHIYUAN_HOME", "zhiyuan_home", "")
    return Path(raw).expanduser() if raw else None


# ---------------------------------------------------------------- 笔记文件

def parse_note(path: Path) -> dict:
    """宽松解析：front matter 坏了也要能读正文，否则用户手改一次就废一篇。"""
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    meta: dict = {}
    match = FRONT_RE.match(text)
    body = text
    if match:
        body = text[match.end():]
        for line in match.group(1).split("\n"):
            if not line or line.startswith((" ", "\t")) or ":" not in line:
                continue  # 嵌套块（source:）不解析，用不到
            key, _, value = line.partition(":")
            meta[key.strip()] = _scalar(value)
    return {
        "id": str(meta.get("id") or path.stem),
        "title": str(meta.get("title") or ""),
        "created": str(meta.get("created") or ""),
        "updated": str(meta.get("updated") or ""),
        "kind": str(meta.get("kind") or ""),
        "status": str(meta.get("status") or ""),
        "tags": meta.get("tags") or [],
        "path": str(path),
        "sections": _sections(body),
        "raw": body.strip(),
    }


def _scalar(value: str):
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("\"'") for item in inner.split(",") if item.strip()]
    return value.strip("\"'")


def _sections(body: str) -> list[dict]:
    out: list[dict] = []
    current: dict | None = None
    for line in body.split("\n"):
        if line.startswith("## "):
            current = {"title": line[3:].strip(), "lines": []}
            out.append(current)
        elif current is not None:
            current["lines"].append(line)
    return [{"title": item["title"], "body": "\n".join(item["lines"]).strip()} for item in out]


def iter_notes(home: Path) -> list[dict]:
    root = home / "notes"
    if not root.is_dir():
        return []
    rows = []
    for path in sorted(root.rglob("*.md")):
        try:
            rows.append(parse_note(path))
        except OSError:
            continue  # 单篇读不了不该让整次列举失败
    rows.sort(key=lambda item: item["created"], reverse=True)
    return rows


def find_note(rows: list[dict], key: str) -> list[dict]:
    key_lower = key.lower()
    exact = [row for row in rows if row["id"] == key]
    if exact:
        return exact
    return [row for row in rows if key_lower in row["title"].lower() or key_lower in row["id"].lower()]


# ---------------------------------------------------------------- HTTP

def http_json(method: str, url: str, payload: dict | None = None,
              timeout: float = TIMEOUT) -> tuple[int, dict]:
    """GET 允许重试一次（只读，重试不会造成副作用）；POST 不重试，避免存出两篇。"""
    attempts = 2 if method == "GET" else 1
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return _request_json(method, url, payload, timeout)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt + 1 < attempts:
                continue
    raise last if last else RuntimeError("请求失败")


def _request_json(method: str, url: str, payload: dict | None, timeout: float) -> tuple[int, dict]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"ok": False, "message": raw[:200] or exc.reason}


def health(args) -> dict:
    try:
        code, data = http_json("GET", f"{base_url(args)}/api/health", timeout=2.5)
    except Exception as exc:  # noqa: BLE001 —— 自检要能报告任何失败，而不是自己崩掉
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    # 端口没人听时，本机代理常常回 502 而不是拒绝连接，不能把 502 当成功
    if code != 200:
        return {"ok": False, "error": f"HTTP {code}: {data.get('message') or '服务未就绪'}"}
    return {"ok": True, "data": data}


# ---------------------------------------------------------------- 输出

def emit(args, text: str) -> None:
    if not getattr(args, "json", False):
        print(text)


def short(text: str, width: int = 28) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= width else text[: width - 1] + "…"


def pretty_time(value: str) -> str:
    return value[:16].replace("T", " ") if value else "—"


# ---------------------------------------------------------------- 子命令

def cmd_doctor(args) -> int:
    home = note_home(args)
    rows = iter_notes(home)
    info = health(args)
    checks: list[tuple[str, bool, str]] = []

    py_ok = sys.version_info >= (3, 11)
    checks.append(("Python", py_ok, f"{sys.version.split()[0]}（需要 ≥ 3.11）"))

    home_ok = (home / "notes").is_dir()
    checks.append(("笔记目录", home_ok, str(home) if home_ok else f"{home} 下没有 notes/"))

    writable = False
    if home_ok:
        try:
            probe = home / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            writable = True
        except OSError:
            writable = False
    checks.append(("可写", writable, "能写才能存新笔记" if writable else "目录不可写"))

    service_ok = bool(info.get("ok"))
    version = ""
    if service_ok:
        version = str((info.get("data") or {}).get("version") or "")
    checks.append(("服务", service_ok,
                   f"{base_url(args)} · v{version}" if service_ok else f"{base_url(args)} 连不上"))

    pages_ok = False
    if service_ok:
        try:
            with urllib.request.urlopen(f"{base_url(args)}/files", timeout=2.5) as resp:
                pages_ok = resp.status == 200
        except Exception:  # noqa: BLE001
            pages_ok = False
    checks.append(("文件页", pages_ok, "/files 可访问" if pages_ok else "/files 打不开"))

    if args.json:
        print(json.dumps({
            "ok": all(ok for _, ok, _ in checks[:2]) and service_ok,
            "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in checks],
            "notes": len(rows),
            "note_home": str(home),
            "base_url": base_url(args),
            "version": version,
        }, ensure_ascii=False, indent=2))
    else:
        print("知源文件 · 自检")
        for name, ok, detail in checks:
            print(f"  {'✓' if ok else '✗'} {name:<10} {detail}")
        print(f"  · 笔记篇数   {len(rows)}")
        if service_ok and rows:
            print("结论：可用（读本地文件，写走服务）")
        elif service_ok:
            print("结论：可用，但笔记库还是空的")
        elif rows:
            print("结论：只能读，存与导出需要服务——先运行 start.bat / start.sh")
        else:
            print("结论：不可用——服务没起，目录里也没有笔记")

    return 0 if (py_ok and home_ok and service_ok) else 1


def cmd_list(args) -> int:
    rows = iter_notes(note_home(args))
    if args.tag:
        rows = [row for row in rows if args.tag in (row["tags"] or [])]
    if args.kind:
        rows = [row for row in rows if row["kind"] == args.kind]
    if args.status:
        rows = [row for row in rows if row["status"] == args.status]
    rows = rows[: args.limit]
    if args.json:
        print(json.dumps({"ok": True, "count": len(rows),
                          "items": [{k: row[k] for k in ("id", "title", "created", "kind",
                                                          "status", "tags")} for row in rows]},
                         ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print(f"没有匹配的笔记（{note_home(args)}）")
        return 0
    print(f"{len(rows)} 篇 · 最近的在前")
    for row in rows:
        print(f"  {row['id']}  {short(row['title'], 26):<26}  {pretty_time(row['created'])}  {row['status']}")
    return 0


def cmd_search(args) -> int:
    words = [word.lower() for word in args.words if word.strip()]
    rows = iter_notes(note_home(args))
    hits = []
    for row in rows:
        haystack = (row["title"] + "\n" + row["raw"]).lower()
        if all(word in haystack for word in words):
            hits.append(row)
    hits = hits[: args.limit]
    if args.json:
        print(json.dumps({"ok": True, "count": len(hits),
                          "items": [{"id": row["id"], "title": row["title"],
                                     "created": row["created"]} for row in hits]},
                         ensure_ascii=False, indent=2))
        return 0
    if not hits:
        print(f"没有命中「{' '.join(args.words)}」（共搜了 {len(rows)} 篇）")
        return 0
    print(f"命中 {len(hits)} 篇")
    for row in hits:
        print(f"\n{row['id']}  {short(row['title'], 30)}  {pretty_time(row['created'])}")
        print(f"  {snippet(row, words)}")
    return 0


def snippet(row: dict, words: list[str], width: int = 56) -> str:
    # 摘录里留着「## 摘要」这种标记没有信息量，先去掉再取上下文
    text = re.sub(r"^#{1,6}\s*", "", row["raw"], flags=re.M)
    text = re.sub(r"\s{2,}", " ", text.replace("\n", " ")).strip()
    lower = text.lower()
    index = min((lower.find(word) for word in words if lower.find(word) >= 0), default=-1)
    if index < 0:
        return short(text, width)
    start = max(0, index - width // 3)
    return ("…" if start else "") + text[start: start + width].strip() + "…"


def cmd_get(args) -> int:
    rows = iter_notes(note_home(args))
    hits = find_note(rows, args.key)
    if not hits:
        print(f"没找到：{args.key}", file=sys.stderr)
        return 2
    if len(hits) > 1:
        print(f"「{args.key}」命中了 {len(hits)} 篇，请换更具体的 id 或标题：", file=sys.stderr)
        for row in hits[:10]:
            print(f"  {row['id']}  {short(row['title'], 30)}", file=sys.stderr)
        return 2
    row = hits[0]
    if args.json:
        print(json.dumps({"ok": True, **{k: row[k] for k in
                                         ("id", "title", "created", "updated", "kind",
                                          "status", "tags", "sections", "path")}},
                         ensure_ascii=False, indent=2))
        return 0
    print(f"{row['title'] or '(无标题)'}")
    print(f"{pretty_time(row['created'])} · {row['kind'] or '—'} · {row['status'] or '—'}"
          f" · {' / '.join(row['tags']) or '无标签'}")
    for section in row["sections"]:
        if not section["body"]:
            continue
        print(f"\n## {section['title']}\n{section['body']}")
    return 0


def cmd_save(args) -> int:
    raw = args.file.read_text(encoding="utf-8") if args.file else sys.stdin.read()
    if not raw.strip():
        print("没有输入：用 --file conv.json 或从标准输入喂 JSON", file=sys.stderr)
        return 1
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"输入不是合法 JSON：{exc}", file=sys.stderr)
        return 1
    if isinstance(payload, list):          # 也接受直接给 messages 数组
        payload = {"messages": payload}
    if not isinstance(payload, dict) or not payload.get("messages"):
        print("缺少 messages：格式为 {\"messages\":[{\"role\":\"user\",\"text\":\"…\"}]}",
              file=sys.stderr)
        return 1
    # 标题/标签/类型走 hint 对象（接口约定），放顶层会被忽略——那会得到「标题自动截断」的假象
    hint = payload.get("hint") if isinstance(payload.get("hint"), dict) else {}
    for extra, flag in ((args.title, "title"), (args.kind, "kind"), (args.status, "status")):
        if extra:
            hint[flag] = extra
    if args.tags:
        hint["tags"] = [part.strip() for part in args.tags.split(",") if part.strip()]
    if args.draft:
        hint.setdefault("status", "draft")
    if hint:
        payload["hint"] = hint
    # 不带 from=chat：走智能体通道，不受「储存对话内容」开关影响
    payload.pop("from", None)

    try:
        code, data = http_json("POST", f"{base_url(args)}/api/notes", payload)
    except Exception as exc:  # noqa: BLE001
        return _save_via_cli(args, raw, exc)

    if code in (200, 201) and data.get("ok"):
        duplicate = data.get("duplicate_of")
        if args.json:
            print(json.dumps({"ok": True, "via": "http", "id": data.get("id"),
                              "title": data.get("title"), "path": data.get("path"),
                              "duplicate_of": duplicate,
                              "messages": data.get("messages")}, ensure_ascii=False, indent=2))
        else:
            suffix = f"（内容相同，指向已有那篇 {duplicate}）" if duplicate else ""
            print(f"已保存 {data.get('id')} · {data.get('title')}{suffix}")
            if data.get("path"):
                print(f"文件：{data['path']}")
        return 0
    if code >= 500:
        # 502/503 基本都是「服务没起」或反代连不上，走离线兜底比报错更有用
        return _save_via_cli(args, raw, RuntimeError(f"HTTP {code}"))

    print(f"保存失败（HTTP {code}）：{data.get('message') or data.get('error')}", file=sys.stderr)
    if code == 403:
        print("提示：带 from=chat 的保存会被「储存对话内容」开关拦下，本命令不应该带它。",
              file=sys.stderr)
    return 1


def _save_via_cli(args, raw: str, exc: Exception) -> int:
    """服务没起时的兜底：如果给了知源源码目录，就用它自己的 CLI 存，逻辑与页面完全一致。"""
    home = zhiyuan_home(args)
    if not home or not (home / "src" / "notes" / "cli.py").exists():
        print(f"连不上服务（{type(exc).__name__}: {exc}）。", file=sys.stderr)
        print("先启动：双击 start.bat（或 python -m src.server），"
              "或用 --zhiyuan-home 指向知源源码目录走离线保存。", file=sys.stderr)
        return 1
    cmd = [sys.executable, "-m", "src.notes", "save", "--from", "-", "--json"]
    for flag, attr in (("--title", "title"), ("--tags", "tags"), ("--kind", "kind"),
                       ("--status", "status")):
        if getattr(args, attr, None):
            cmd += [flag, getattr(args, attr)]
    env = {**os.environ, "PYTHONPATH": str(home),
           "NOTE_HOME": str(note_home(args)), "PYTHONUTF8": "1"}
    proc = subprocess.run(cmd, cwd=str(home), env=env, input=raw,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    if proc.returncode != 0:
        print(f"离线保存失败：{proc.stderr.strip()[:300]}", file=sys.stderr)
        return 1
    # CLI 的 --json 是缩进过的多行，按整段解析；解析不了再退回最后一行
    text = proc.stdout.strip()
    data: dict | None = None
    for candidate in (text, text.splitlines()[-1] if text else ""):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            data = parsed
            break
    if data is None:
        print(text[:300])
        return 0
    if args.json:
        print(json.dumps({"ok": True, "via": "cli", **{k: data.get(k) for k in
                                                       ("id", "title", "path")}},
                         ensure_ascii=False, indent=2))
    else:
        print(f"已保存（离线）{data.get('id')} · {data.get('title')}")
    return 0


def cmd_export(args) -> int:
    url = f"{base_url(args)}/api/notes/export?format={args.format}"
    try:
        code, data = http_json("GET", url)
    except Exception as exc:  # noqa: BLE001
        print(f"连不上服务（{type(exc).__name__}: {exc}），导出必须由服务生成。", file=sys.stderr)
        return 1
    if code != 200 or not data.get("ok"):
        hint = "（导出要靠服务生成，先启动 start.bat）" if code >= 500 else ""
        print(f"导出失败（HTTP {code}）：{data.get('message') or data.get('error')}{hint}",
              file=sys.stderr)
        return 1
    content = data.get("content") or ""
    if args.out:
        target = Path(args.out).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
        print(f"已导出 {data.get('count', 0)} 篇 → {target}（{target.stat().st_size} 字节）")
    else:
        print(content)
    return 0


def cmd_open(args) -> int:
    url = f"{base_url(args)}/{args.page}"
    if args.no_launch:
        print(url)
        return 0
    try:
        opened = webbrowser.open(url)
    except Exception:  # noqa: BLE001
        opened = False
    print(url if opened else f"{url}\n（没有可用的浏览器，链接已打印，手动打开即可）")
    return 0


# ---------------------------------------------------------------- 入口

def _common_flags() -> argparse.ArgumentParser:
    """全局开关同时挂到主命令和子命令上：`zy --json list` 与 `zy list --json` 都得能用。
    default=SUPPRESS 是必须的——否则子命令的默认值会把主命令里已经解析到的值覆盖掉。"""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default=argparse.SUPPRESS,
                        help=f"服务地址，默认 {DEFAULT_BASE}")
    common.add_argument("--home", default=argparse.SUPPRESS, help="笔记根目录，默认 ~/agent-notes")
    common.add_argument("--zhiyuan-home", default=argparse.SUPPRESS,
                        help="知源源码目录（服务没起时用于离线保存）")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="输出 JSON，便于程序消费")
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _common_flags()
    parser = argparse.ArgumentParser(
        prog="zy", parents=[common],
        description="知源文件：列笔记、搜内容、读全文、存对话、导出、打开页面")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", parents=[common], help="自检：Python、目录、服务、文件页")

    p_list = sub.add_parser("list", parents=[common], help="列出笔记")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--tag")
    p_list.add_argument("--kind")
    p_list.add_argument("--status")

    p_search = sub.add_parser("search", parents=[common], help="按关键词搜索（全部命中才算）")
    p_search.add_argument("words", nargs="+")
    p_search.add_argument("--limit", type=int, default=20)

    p_get = sub.add_parser("get", parents=[common], help="按 id 或标题片段读一篇")
    p_get.add_argument("key")

    p_save = sub.add_parser("save", parents=[common], help="把一段对话存成笔记")
    p_save.add_argument("--file", type=Path, help="对话 JSON 文件；省略则读标准输入")
    p_save.add_argument("--title")
    p_save.add_argument("--tags", help="逗号分隔")
    p_save.add_argument("--kind", choices=["decision", "howto", "reference", "qa", "log"])
    p_save.add_argument("--status", choices=["draft", "final", "archived"])
    p_save.add_argument("--draft", action="store_true")

    p_export = sub.add_parser("export", parents=[common], help="导出全部（json / html）")
    p_export.add_argument("--format", choices=["json", "html"], default="json")
    p_export.add_argument("--out", help="写入文件；省略则打印到标准输出")

    p_open = sub.add_parser("open", parents=[common], help="打开页面（默认 /files）")
    p_open.add_argument("--page", choices=["files", "ask", "kb"], default="files")
    p_open.add_argument("--no-launch", action="store_true", help="只打印地址，不拉起浏览器")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # 控制台 cp936 下中文不炸
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    args.json = getattr(args, "json", False)   # 全局开关默认不存在，这里补齐
    handler = {
        "doctor": cmd_doctor, "list": cmd_list, "search": cmd_search, "get": cmd_get,
        "save": cmd_save, "export": cmd_export, "open": cmd_open,
    }[args.command]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
