"""把 README 与 docs/*.md 生成一个可离线浏览的静态文档站。

为什么需要：新用户要在 1700 行的 README 里找入口，集成方要读源码才能确认字段。
文档本身是齐的（16 篇），缺的是「能点开、能跳转、有目录」这一层。
托管 docs 站要额外的域名与构建服务，与单机定位不符；静态站点生成到仓库里，
双击就能看，也能直接扔到任意静态托管上。

用法：
    python tools/build_docs_site.py                 # 输出到 docs/site/
    python tools/build_docs_site.py --out 某目录
    python tools/build_docs_site.py --check         # 只校验，不写文件（CI 用）

设计取舍：
- 生成物进仓库：这样没有 node/python 环境的人也能看。缺点是改文档要重跑，
  所以 `--check` 在 CI 里跑一次，生成物过期就让流水线红。
- 不引第三方 Markdown：见 `src/mdrender.py` 的说明。
- 不做搜索：16 篇文档 + 一个目录页，浏览器自带的页内查找够用；
  真做全文搜索就要维护索引，反而成了另一个需要更新的东西。
"""
from __future__ import annotations

import argparse
import html
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mdrender import render  # noqa: E402
from src.version import __version__  # noqa: E402

SITE_CSS = """
:root{--bg:#fbfbf9;--surface:#fff;--text:#1c2521;--muted:#5b6b64;--line:#e2e6e2;
--brand:#2f6f5e;--code-bg:#f4f6f4}
@media (prefers-color-scheme: dark){
:root{--bg:#141917;--surface:#1b211e;--text:#e8ede9;--muted:#9aa8a1;--line:#2c3431;
--brand:#82c0a9;--code-bg:#202724}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:16px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
a{color:var(--brand)}
.layout{display:flex;min-height:100vh}
.side{width:260px;flex:0 0 260px;border-right:1px solid var(--line);padding:22px 16px;
position:sticky;top:0;height:100vh;overflow:auto;background:var(--surface)}
.side h1{font-size:15px;margin:0 0 4px}
.side .ver{font-size:12px;color:var(--muted);margin-bottom:16px}
.side a{display:block;padding:5px 8px;border-radius:6px;text-decoration:none;
font-size:14px;color:var(--text)}
.side a:hover{background:var(--code-bg)}
.side a.on{background:var(--code-bg);color:var(--brand);font-weight:600}
.main{flex:1;min-width:0;padding:34px 40px 80px;max-width:920px}
.main h1{font-size:28px;line-height:1.35;margin:0 0 18px}
.main h2{font-size:21px;margin:34px 0 12px;padding-top:8px;border-top:1px solid var(--line)}
.main h3{font-size:17px;margin:24px 0 8px}
.main h4{font-size:15px;margin:20px 0 6px}
p,li{overflow-wrap:anywhere}
code{background:var(--code-bg);padding:1px 5px;border-radius:4px;font-size:13.5px;
font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
pre{background:var(--code-bg);padding:14px 16px;border-radius:10px;overflow:auto;
border:1px solid var(--line)}
pre code{background:none;padding:0;font-size:13px;line-height:1.6}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:14px;display:block;overflow:auto}
th,td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
th{background:var(--code-bg);font-weight:600;white-space:nowrap}
blockquote{margin:14px 0;padding:8px 14px;border-left:3px solid var(--brand);
background:var(--code-bg);border-radius:0 8px 8px 0;color:var(--muted)}
hr{border:0;border-top:1px solid var(--line);margin:26px 0}
.foot{margin-top:50px;padding-top:14px;border-top:1px solid var(--line);
font-size:12.5px;color:var(--muted)}
@media (max-width:820px){
.layout{display:block}
.side{position:static;width:auto;height:auto;border-right:0;border-bottom:1px solid var(--line)}
.main{padding:22px 18px 60px}
}
"""


def page(title: str, body: str, nav: list[tuple[str, str]], active: str) -> str:
    links = "".join(
        f'<a href="{html.escape(href)}"{" class=\"on\"" if href == active else ""}>'
        f"{html.escape(label)}</a>"
        for label, href in nav)
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{SITE_CSS}</style></head><body>"
        '<div class="layout"><aside class="side">'
        '<h1>记忆文档 · 文档站</h1>'
        f'<div class="ver">v{html.escape(__version__)}</div>'
        f"{links}</aside><main class=\"main\">{body}"
        '<div class="foot">由 tools/build_docs_site.py 从 Markdown 生成，'
        "请勿直接编辑这里的 HTML。</div></main></div></body></html>"
    )


def sources() -> list[tuple[str, Path]]:
    """要收进站点的文档：(标签, 路径)。

    顺序刻意是「先上手、后细节」：README 打头，然后按 docs/ 里的文件名排序
    （它们本来就带编号或语义前缀）。
    """
    items: list[tuple[str, Path]] = [("README · 总览", ROOT / "README.md")]
    for path in sorted((ROOT / "docs").glob("*.md")):
        items.append((path.stem, path))
    return items


def build(out_dir: Path) -> tuple[int, int]:
    """生成站点，返回 (页数, 总字节)。"""
    items = sources()
    pages: list[tuple[str, str, str]] = []      # (标签, 文件名, HTML 正文)
    for label, path in items:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"  跳过 {path.name}：{exc}")
            continue
        name = "index.html" if path.name == "README.md" else path.stem + ".html"
        pages.append((label, name, render(text)))

    nav = [(label, name) for label, name, _body in pages]
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for label, name, body in pages:
        target = out_dir / name
        content = page(f"{label} · 文档站", body, nav, name)
        target.write_text(content, encoding="utf-8", newline="\n")
        total += len(content)
    return len(pages), total


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="生成静态文档站")
    parser.add_argument("--out", default=str(ROOT / "docs" / "site"))
    parser.add_argument("--check", action="store_true",
                        help="只校验生成物是否最新（CI 用），不写文件")
    args = parser.parse_args(argv)

    items = sources()
    if not items:
        print("没有可用的 Markdown 源")
        return 1
    if args.check:
        # 校验方式：生成到临时目录，与仓库里的逐字节比对。
        # 只比 mtime 不够——复制仓库不会保留时间戳，那样 CI 永远红。
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            count, _ = build(Path(tmp))
            stale = []
            for path in Path(tmp).iterdir():
                target = Path(args.out) / path.name
                if not target.exists() or target.read_text(encoding="utf-8") != path.read_text(encoding="utf-8"):
                    stale.append(path.name)
        if stale:
            print("文档站已过期：" + ", ".join(sorted(stale)[:6])
                  + f"（共 {len(stale)} 个）。请运行 python tools/build_docs_site.py")
            return 1
        print(f"文档站是最新的（{count} 页）")
        return 0

    count, size = build(Path(args.out))
    print(f"已生成 {count} 页，共 {size / 1024:.1f} KB → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
