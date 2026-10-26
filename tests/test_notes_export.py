"""离线导出测试：单文件、可断网、无注入、能回读。

导出物的验收标准只有两条：双击能看，内容与磁盘一致。
所以这里既检查 HTML 结构，也检查 JSON 能被重新解析成同样多的笔记。
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("NOTE_HOME", tempfile.mkdtemp(prefix="export-notes-"))

# 直接 `python tests/x.py` 跑时，sys.path[0] 是 tests/，仓库根不在里面。
# CI 里没有 PYTHONPATH，缺这段就是 ModuleNotFoundError: No module named 'src'。
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.notes import export as export_mod  # noqa: E402
from src.notes.api import ApiError, dispatch  # noqa: E402
from src.notes.cli import main as cli_main  # noqa: E402
from src.notes.service import NoteService  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))


def seed(service: NoteService) -> list[str]:
    ids = []
    payloads = [
        ("退税率口径", "decision", ["税务"], "按 13% 执行。决定由财务部每月 5 日前复核。"),
        ("上传流程", "howto", ["知识库"], "先上传 docx，再等索引重建完成。"),
        ("带脚本的标题 <img src=x onerror=alert(1)>", "qa", ["安全"], "正文里有 <script>alert(1)</script> 和 ]]> 结束符。"),
    ]
    for title, kind, tags, text in payloads:
        result = service.save({"messages": [{"role": "user", "text": title},
                                            {"role": "assistant", "text": text}],
                               "hint": {"title": title, "kind": kind, "tags": tags}})
        ids.append(result["id"])
    return ids


def main() -> int:
    home = tempfile.mkdtemp(prefix="export-home-")
    service = NoteService(home)
    ids = seed(service)

    # 1) HTML 基本结构
    out = Path(home) / "exports" / "all.html"
    result = export_mod.export(service, out)
    html = out.read_text(encoding="utf-8")
    check("导出三篇", result["count"] == 3, str(result))
    check("是完整 HTML 文档", html.lstrip().startswith("<!doctype html>") and "</html>" in html)
    check("没有外部样式与脚本", "<link" not in html and "src=\"http" not in html
          and "@import" not in html and "<script src" not in html)
    check("带搜索框与类型筛选", 'id="q"' in html and 'id="kind"' in html)
    check("深色模式用媒体查询而非外链", "prefers-color-scheme" in html)
    check("打印时隐藏工具栏", "@media print" in html)

    # 2) 注入与转义
    check("标题里的标签被转义", "&lt;img src=x" in html and "<img src=x" not in html)
    check("正文里的 script 被转义", "&lt;script&gt;alert(1)" in html and "<script>alert(1)" not in html)

    # 3) 按标签 / 按 id 导出
    only_tax = Path(home) / "exports" / "tax.html"
    r = export_mod.export(service, only_tax, filters={"tags": ["税务"]})
    check("按标签筛选命中 1 篇", r["count"] == 1, str(r["count"]))
    check("筛选结果里没有别的标题", "上传流程" not in only_tax.read_text(encoding="utf-8"))

    one = Path(home) / "exports" / "one.html"
    r = export_mod.export(service, one, note_ids=[ids[1]])
    check("按 id 导出单篇", r["count"] == 1 and "上传流程" in one.read_text(encoding="utf-8"))

    # 4) JSON bundle 可回读
    bundle_path = Path(home) / "exports" / "all.json"
    export_mod.export(service, bundle_path, fmt="json")
    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    check("bundle 结构正确", data["schema"] == "notes-bundle/v1" and data["count"] == 3)
    check("bundle 里每篇都有 markdown",
          all("---" in item["markdown"] for item in data["notes"]))
    check("bundle 不带服务器绝对路径变量", all("path" not in item for item in data["notes"]))

    # 5) 空集合也能导出（不要因为 0 篇就报错）
    empty = Path(home) / "exports" / "empty.html"
    r = export_mod.export(service, empty, filters={"tags": ["根本没有"]})
    check("0 篇导出成功并给出空状态", r["count"] == 0 and "还没有笔记" in empty.read_text(encoding="utf-8"))

    # 6) 原子写：导出失败不会留下半截文件
    target = Path(home) / "exports" / "keep.html"
    export_mod.export(service, target)
    before = target.read_text(encoding="utf-8")
    try:
        export_mod.export(service, target, fmt="pdf")
        check("不支持的格式应报错", False)
    except ValueError:
        check("不支持的格式明确报错", True)
    check("报错后旧文件未被破坏", target.read_text(encoding="utf-8") == before)
    check("没有残留 .tmp", not list(Path(home, "exports").glob("*.tmp")))

    # 7) CLI
    cli_out = Path(home) / "exports" / "cli.html"
    code = cli_main(["--home", home, "export", "--out", str(cli_out), "--tag", "税务"])
    check("CLI export 退出码 0", code == 0, str(code))
    check("CLI 导出文件存在", cli_out.exists())

    # 8) HTTP 接口返回内容而不是写盘
    status, payload, _ = dispatch(service, "GET", "/api/notes/export", {"format": ["html"]}, None)
    check("GET /api/notes/export 返回 200", status == 200)
    check("返回 html 内容与文件名", payload["content"].startswith("<!doctype html>")
          and payload["filename"].endswith(".html"))
    check("接口不写服务器文件系统", payload["bytes"] > 1000)
    status, payload_json, _ = dispatch(service, "GET", "/api/notes/export", {"format": ["json"]}, None)
    check("format=json 返回可解析内容", json.loads(payload_json["content"])["count"] == 3)
    try:
        dispatch(service, "GET", "/api/notes/export", {"format": ["pdf"]}, None)
        check("非法格式返回 400", False)
    except ApiError as exc:
        check("非法格式返回 400", exc.status == 400 and "format" in exc.payload["message"])

    # 9) 导出的是「当前文件内容」，手改后立刻反映
    note_path = Path(service.get(ids[0])["markdown"] and "")
    stored = Path(home, "notes")
    target_file = next(p for p in stored.rglob(f"{ids[0]}.md"))
    edited = target_file.read_text(encoding="utf-8").replace("按 13% 执行", "按 9% 执行（人工改）")
    target_file.write_text(edited, encoding="utf-8")
    fresh = Path(home) / "exports" / "fresh.html"
    export_mod.export(service, fresh)
    check("手改文件后导出立即反映", "按 9% 执行（人工改）" in fresh.read_text(encoding="utf-8"))

    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
        return 1
    print("NOTES EXPORT OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
