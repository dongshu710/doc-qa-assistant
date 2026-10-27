"""终端客户端：没有图形环境也能用「记忆文档」。

为什么还要一个 CLI：不是所有 Python 都带 Tkinter（精简发行版、服务器、容器里通常没有），
而「不依赖浏览器」这句话不能只在装了 Tk 的机器上成立。CLI 只依赖标准库与本地 HTTP 接口，
SSH 里、CI 里、没有桌面的机器上都能跑。

用法：
    python -m src.client status
    python -m src.client ask "稳盈系列的起购金额是多少" --save
    python -m src.client notes --limit 20
    python -m src.client show <note_id>
    python -m src.client cat notes/2026/10/xxx.md
    python -m src.client write notes/2026/10/xxx.md --content "# 新内容"
    python -m src.client threads
    python -m src.client thread <thread_id>
    python -m src.client backups
    python -m src.client backup --note "手动备份"
    python -m src.client restore <backup.zip> --force
"""
from __future__ import annotations

import argparse
import sys

from .client_api import DEFAULT_BASE, Client, ClientError


def _client(args) -> Client:
    return Client(args.base, args.key)


def _print_note(item: dict) -> None:
    title = item.get("title") or "(无标题)"
    print(f"{item.get('id')}  {title}  [{item.get('status') or '-'}]  {item.get('updated') or ''}")


def cmd_status(args) -> int:
    client = _client(args)
    health = client.health()
    settings = client.settings()
    notes = settings.get("notes") or {}
    runtime = health.get("runtime") or {}
    print(f"服务      {client.base}")
    print(f"版本      {health.get('version')}")
    print(f"模型      {health.get('model')}（{'在线' if health.get('llm_ready') else '离线抽取'}）")
    print(f"知识块    {health.get('chunks')} 段 · 检索 {health.get('retrieval')}")
    print(f"存储区    {notes.get('home_effective')}")
    print(f"笔记      {notes.get('count', 0)} 篇")
    print(f"运行模式  {runtime.get('mode')} · 状态后端 {runtime.get('state_backend')}")
    for warning in runtime.get("warnings") or []:
        print(f"警告      {warning}")
    return 0


def cmd_ask(args) -> int:
    client = _client(args)
    result = client.ask(args.query, args.session)
    print(result.get("answer") or "")
    print()
    for item in result.get("citations") or []:
        print(f"[{item.get('ref')}] {item.get('title')} · {item.get('section')}")
    meta = [f"mode={result.get('mode')}", f"{result.get('latency_ms')} ms"]
    if result.get("degraded"):
        meta.append(f"degraded={result.get('degrade_reason')}")
    rate = result.get("citation_support_rate")
    if rate is not None:
        meta.append(f"citation_support={rate:.0%}")
    print(" · ".join(meta))
    if args.save:
        saved = client.save_note(args.query, result.get("answer") or "")
        print(f"已存为笔记 {saved.get('id')}" if saved.get("id") else "未保存（内容重复或已关闭）")
    return 0


def cmd_notes(args) -> int:
    client = _client(args)
    items = client.notes(args.limit)
    for item in items:
        _print_note(item)
    print(f"\n共 {len(items)} 篇")
    return 0


def cmd_show(args) -> int:
    client = _client(args)
    note = client.note(args.id)
    print(f"标题：{note.get('title')}")
    print(f"路径：{note.get('path')}  rev={note.get('rev')}")
    print("-" * 40)
    print(note.get("markdown") or "")
    return 0


def cmd_cat(args) -> int:
    print(_client(args).read_file(args.path)["content"], end="")
    return 0


def cmd_write(args) -> int:
    client = _client(args)
    if args.from_file:
        content = sys.stdin.read() if args.from_file == "-" else open(
            args.from_file, encoding="utf-8").read()
    elif args.content is not None:
        content = args.content
    else:
        print("请用 --content 或 --from 指定内容", file=sys.stderr)
        return 2
    current = client.read_file(args.path)
    result = client.write_file(args.path, content, current["rev"])
    print(f"已写入 {args.path}  rev={result['rev']}")
    return 0


def cmd_threads(args) -> int:
    items = _client(args).threads(args.limit)
    for item in items:
        print(f"{item.get('id')}  {item.get('title') or '新对话'}  {item.get('turns')} 轮")
    print(f"\n共 {len(items)} 条")
    return 0


def cmd_thread(args) -> int:
    thread = _client(args).thread(args.id)
    print(f"{thread.get('title')}  {thread.get('updated')}")
    for turn in thread.get("turns") or []:
        print("\n问：" + str(turn.get("q") or ""))
        answer = (turn.get("d") or {}).get("answer")
        if answer:
            print("答：" + str(answer))
    return 0


def cmd_backups(args) -> int:
    items = _client(args).backups()
    for item in items:
        print(f"{item.get('name')}  {item.get('bytes', 0) // 1024} KB  {item.get('created')}")
    print(f"\n共 {len(items)} 个")
    return 0


def cmd_backup(args) -> int:
    result = _client(args).backup(args.note)
    print(f"已备份 {result.get('files')} 个文件 → {result.get('name')}"
          f"（{result.get('bytes', 0) // 1024} KB）")
    return 0


def cmd_restore(args) -> int:
    result = _client(args).restore(args.name, force=args.force)
    print(result.get("message") or "已恢复")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.client", description="记忆文档 · 终端客户端")
    parser.add_argument("--base", default=DEFAULT_BASE, help="服务地址")
    parser.add_argument("--key", default="", help="服务端启用 API_KEYS 时的密钥")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="服务与存储状态").set_defaults(func=cmd_status)

    ask = sub.add_parser("ask", help="提问")
    ask.add_argument("query")
    ask.add_argument("--session", default=None, help="多轮会话 id")
    ask.add_argument("--save", action="store_true", help="顺便存成笔记")
    ask.set_defaults(func=cmd_ask)

    notes = sub.add_parser("notes", help="笔记列表")
    notes.add_argument("--limit", type=int, default=20)
    notes.set_defaults(func=cmd_notes)

    show = sub.add_parser("show", help="看一篇笔记")
    show.add_argument("id")
    show.set_defaults(func=cmd_show)

    cat = sub.add_parser("cat", help="打印存储区里的原文件")
    cat.add_argument("path")
    cat.set_defaults(func=cmd_cat)

    write = sub.add_parser("write", help="写原文件（自动带 rev）")
    write.add_argument("path")
    write.add_argument("--content", default=None)
    write.add_argument("--from", dest="from_file", default=None, help="从文件或 - 读取")
    write.set_defaults(func=cmd_write)

    threads = sub.add_parser("threads", help="会话列表")
    threads.add_argument("--limit", type=int, default=20)
    threads.set_defaults(func=cmd_threads)

    thread = sub.add_parser("thread", help="看一条会话")
    thread.add_argument("id")
    thread.set_defaults(func=cmd_thread)

    sub.add_parser("backups", help="备份列表").set_defaults(func=cmd_backups)

    backup = sub.add_parser("backup", help="立即备份")
    backup.add_argument("--note", default="终端手动备份")
    backup.set_defaults(func=cmd_backup)

    restore = sub.add_parser("restore", help="恢复某个备份")
    restore.add_argument("name")
    restore.add_argument("--force", action="store_true")
    restore.set_defaults(func=cmd_restore)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ClientError as exc:
        hint = ""
        if exc.is_offline:
            hint = "\n先启动服务：python -m src.server"
        elif exc.status == 401:
            hint = "\n服务端已启用 API Key：加 --key <你的 Key>"
        print(f"错误：{exc}{hint}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
