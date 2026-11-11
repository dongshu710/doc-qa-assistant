"""极简 Markdown → HTML（零第三方依赖）。

为什么自己写：`docs/*.md` 要变成可浏览的站点，而引 `markdown`/`mistune` 会破坏
「核心路径零依赖」这条铁律。本项目文档的语法是收敛的（标题、列表、表格、围栏代码、
行内代码、粗体、链接），一个 200 行的实现足够，不需要通用解析器。

刻意不支持：HTML 块（我们的文档里没有，且允许内联 HTML 等于给出一个注入面）、
脚注、定义列表、引用式链接、嵌套列表的深度缩进。遇到不认识的语法就当普通段落，
**不报错**——文档站生成失败不该挡住任何别的事。

安全性：所有文本先转义再拼标签。文档内容虽然是自己仓库里的，
但这个渲染器也会被 `/report` 之类的路径复用，别留「以后接用户输入」的坑。
"""
from __future__ import annotations

import html
import re

_CODE_FENCE = re.compile(r"^```(\w*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_UL = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_TABLE_SEP = re.compile(r"^\|?[\s:|-]+\|[\s:|-]*$")
_HR = re.compile(r"^\s*(---|\*\*\*|___)\s*$")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _inline(text: str) -> str:
    """行内语法。先转义再替换，替换产生的标签不会被二次转义。"""
    out = html.escape(text, quote=False)
    # 行内代码要最先处理，否则代码里的 * 会被当成斜体、`<div>` 会被当标签
    codes: list[str] = []

    def stash(match):
        codes.append(match.group(1))
        return f"\x00{len(codes) - 1}\x00"

    out = _INLINE_CODE.sub(stash, out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _ITALIC.sub(r"<em>\1</em>", out)
    out = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', out)
    for index, code in enumerate(codes):
        out = out.replace(f"\x00{index}\x00", f"<code>{code}</code>")
    return out


def _table(lines: list[str]) -> str:
    """把 GFM 表格转成 `<table>`。第一行是表头，第二行是分隔行（已由调用方确认）。"""
    def cells(line: str) -> list[str]:
        row = line.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|"):
            row = row[:-1]
        return [cell.strip() for cell in row.split("|")]

    head = cells(lines[0])
    body = [cells(line) for line in lines[2:]]
    out = ["<table><thead><tr>"] + [f"<th>{_inline(c)}</th>" for c in head] + ["</tr></thead><tbody>"]
    for row in body:
        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def render(text: str) -> str:
    """Markdown → HTML 片段（不含 `<html>` 骨架）。"""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    index = 0
    paragraph: list[str] = []
    list_kind = ""
    list_open = False

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append("<p>" + _inline(" ".join(item.strip() for item in paragraph)) + "</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal list_kind, list_open
        if list_open:
            out.append(f"</{list_kind}>")
            list_open = False
            list_kind = ""

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        fence = _CODE_FENCE.match(stripped)
        if fence:
            flush_paragraph()
            close_list()
            language = fence.group(1)
            index += 1
            block: list[str] = []
            while index < len(lines) and not _CODE_FENCE.match(lines[index].strip()):
                block.append(lines[index])
                index += 1
            index += 1        # 跳过结束围栏
            cls = f' class="lang-{html.escape(language)}"' if language else ""
            out.append(f"<pre><code{cls}>" + html.escape("\n".join(block)) + "</code></pre>")
            continue

        if not stripped:
            flush_paragraph()
            close_list()
            index += 1
            continue

        if _HR.match(stripped):
            flush_paragraph()
            close_list()
            out.append("<hr>")
            index += 1
            continue

        heading = _HEADING.match(stripped)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            body = heading.group(2).strip()
            anchor = re.sub(r"[^\w\u4e00-\u9fff]+", "-", body).strip("-").lower() or f"h{index}"
            out.append(f'<h{level} id="{anchor}">{_inline(body)}</h{level}>')
            index += 1
            continue

        # 表格：当前行含 | 且下一行是分隔行
        if "|" in stripped and index + 1 < len(lines) and _TABLE_SEP.match(lines[index + 1].strip()):
            flush_paragraph()
            close_list()
            block = [line, lines[index + 1]]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                block.append(lines[index])
                index += 1
            out.append(_table(block))
            continue

        if stripped.startswith(">"):
            flush_paragraph()
            close_list()
            quote: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip().lstrip(">").strip())
                index += 1
            out.append("<blockquote>" + _inline(" ".join(quote)) + "</blockquote>")
            continue

        bullet = _UL.match(line)
        ordered = _OL.match(line)
        if bullet or ordered:
            flush_paragraph()
            kind = "ul" if bullet else "ol"
            if list_open and list_kind != kind:
                close_list()
            if not list_open:
                out.append(f"<{kind}>")
                list_open = True
                list_kind = kind
            body = bullet.group(2) if bullet else ordered.group(3)
            out.append(f"<li>{_inline(body)}</li>")
            index += 1
            continue

        paragraph.append(line)
        index += 1

    flush_paragraph()
    close_list()
    return "\n".join(out)
