"""命令行入口：`python -m src.notes`。

CLI 是兜底通道——任何只能执行命令的智能体都能用它，不依赖 MCP / HTTP。
输出同时提供人读与 `--json` 两种形态，机器消费不会被中文提示干扰。
"""

from __future__ import annotations

import argparse
import json
import sys

from .model import NoteError
from .service import NoteService
from .store import NoteNotFound, StoreBusy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notes", description="把智能体对话整理成个人笔记（文件为唯一真相）")
    parser.add_argument("--home", help="笔记根目录，默认取 NOTE_HOME 或 ~/agent-notes")
    sub = parser.add_subparsers(dest="command", required=True)

    save = sub.add_parser("save", help="从 JSON 保存一段对话")
    save.add_argument("--from", dest="source", help="JSON 文件路径；用 - 表示标准输入（默认）")
    save.add_argument("--kind", choices=["decision", "howto", "reference", "qa", "log"])
    save.add_argument("--title")
    save.add_argument("--tags", help="逗号分隔，例如 税务,出口退税")
    save.add_argument("--status", choices=["draft", "final", "archived"])
    save.add_argument("--select-indices", help="只存第几条，逗号分隔，从 1 开始")
    save.add_argument("--select-range", help="只存区间，如 2-5（含两端）")
    save.add_argument("--select-keyword", help="只存包含该关键词的消息")
    save.add_argument("--keep-raw", action="store_true", help="保留对话原文")
    save.add_argument("--no-raw", action="store_true", help="不保留原文（默认）")
    save.add_argument("--digest", choices=["rule", "auto", "llm"],
                      help="摘要引擎：rule=纯规则（默认）；auto=有模型就用、失败回落；llm=必须成功")
    save.add_argument("--draft", action="store_true", help="只预览，不写盘")
    save.add_argument("--json", action="store_true", help="输出 JSON")

    listing = sub.add_parser("list", help="列出笔记")
    listing.add_argument("--tag", action="append", default=[], help="按标签过滤，可重复")
    listing.add_argument("--kind", choices=["decision", "howto", "reference", "qa", "log"])
    listing.add_argument("--status", choices=["draft", "final", "archived"])
    listing.add_argument("--since", help="起始日期，如 2026-10-01")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--json", action="store_true")

    getter = sub.add_parser("get", help="按 id 读取一篇")
    getter.add_argument("id")
    getter.add_argument("--section", help="只输出某一节，如 摘要")
    getter.add_argument("--json", action="store_true")

    export = sub.add_parser("export", help="导出为单文件 HTML 或 JSON")
    export.add_argument("--out", required=True, help="输出路径，例如 exports/all.html")
    export.add_argument("--format", choices=["html", "json"], default="html")
    export.add_argument("--id", action="append", default=[], help="只导出这几篇，可重复")
    export.add_argument("--tag", action="append", default=[], help="按标签筛选，可重复")
    export.add_argument("--since", help="起始日期，如 2026-10-01")
    export.add_argument("--title", default="我的笔记", help="导出文件里的标题")
    export.add_argument("--json", action="store_true", help="输出 JSON 结果")

    sub.add_parser("rebuild", help="从磁盘重建索引")
    sub.add_parser("stats", help="统计数量与标签")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = NoteService(args.home)
    try:
        if args.command == "save":
            return _cmd_save(service, args)
        if args.command == "list":
            return _cmd_list(service, args)
        if args.command == "get":
            return _cmd_get(service, args)
        if args.command == "export":
            return _cmd_export(service, args)
        if args.command == "rebuild":
            total = service.store.rebuild()
            print(f"索引已重建：{total} 篇" if not getattr(args, "json", False) else json.dumps({"ok": True, "notes": total}))
            return 0
        if args.command == "stats":
            data = service.stats()
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
    except NoteNotFound as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 5
    except StoreBusy as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 4
    except NoteError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    return 2


def _cmd_save(service: NoteService, args) -> int:
    payload = _read_payload(args.source)
    select = dict(payload.get("select") or {})
    if args.select_indices:
        select.update({"mode": "indices", "indices": _split_ints(args.select_indices)})
    elif args.select_range:
        start, _, end = args.select_range.partition("-")
        select.update({"mode": "range", "start": int(start), "end": int(end or start)})
    elif args.select_keyword:
        select.update({"mode": "keyword", "keyword": args.select_keyword})
    payload["select"] = select
    hint = dict(payload.get("hint") or {})
    if args.title:
        hint["title"] = args.title
    if args.tags:
        hint["tags"] = [item.strip() for item in args.tags.split(",") if item.strip()]
    if args.kind:
        hint["kind"] = args.kind
    if args.status:
        hint["status"] = args.status
    payload["hint"] = hint

    keep_raw = True if args.keep_raw else False if args.no_raw else None
    result = service.save(payload, commit=not args.draft, keep_raw=keep_raw,
                          digest_mode=args.digest)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if result["duplicate_of"]:
        print(f"已存在同内容笔记：{result['duplicate_of']}")
    state = "草稿（未写盘）" if args.draft else "已保存"
    print(f"{state} {result['id']}")
    print(f"标题：{result['title']}")
    meta = (f"类型：{result['kind']}  标签：{','.join(result['tags']) or '无'}  "
            f"消息：{result['messages']} 条  摘要：{result['digest']}")
    print(meta + ("  已截断" if result["truncated"] else ""))
    if result.get("digest_fallback"):
        print(f"注意：模型摘要不可用（{result['digest_fallback']}），本篇由规则引擎生成")
    if result["path"]:
        print(f"文件：{result['path']}")
    if args.draft or not result["path"]:
        print("\n" + result["markdown"])
    return 0


def _cmd_list(service: NoteService, args) -> int:
    rows = service.list(tags=args.tag or None, kind=args.kind, status=args.status,
                        since=args.since, limit=args.limit)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("没有匹配的笔记")
        return 0
    for row in rows:
        tags = f"  [{','.join(row.get('tags') or [])}]" if row.get("tags") else ""
        print(f"{row.get('id')}  {str(row.get('created') or '')[:10]}  {row.get('title')}{tags}")
    print(f"\n共 {len(rows)} 篇")
    return 0


def _cmd_get(service: NoteService, args) -> int:
    data = service.get(args.id)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if args.section:
        body = next((item["body"] for item in data["sections"] if item["title"] == args.section), "")
        print(body or f"（没有「{args.section}」这一节）")
        return 0
    print(data["markdown"])
    return 0


def _cmd_export(service: NoteService, args) -> int:
    from . import export as export_mod
    result = export_mod.export(
        service, args.out, note_ids=args.id or None, fmt=args.format,
        filters={"tags": args.tag or None, "since": args.since}, title=args.title)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f"已导出 {result['count']} 篇 → {result['path']}（{result['bytes'] / 1024:.1f} KB）")
    if result["format"] == "html":
        print("单文件，可直接双击打开；断网也能读。")
    return 0


def _read_payload(path: str | None) -> dict:
    if not path or path == "-":
        raw = sys.stdin.read()
    else:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
    if not raw.strip():
        raise NoteError("没有读到内容：请通过 --from 指定文件，或用管道传入 JSON")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NoteError(f"JSON 解析失败：{exc.msg}（第 {exc.lineno} 行）") from exc
    if not isinstance(data, dict):
        raise NoteError("JSON 顶层必须是对象，例如 {\"messages\": [...]}")
    return data


def _split_ints(raw: str) -> list[int]:
    try:
        return [int(item) for item in raw.replace("，", ",").split(",") if item.strip()]
    except ValueError:
        raise NoteError(f"下标必须是整数：{raw}") from None


if __name__ == "__main__":
    raise SystemExit(main())
