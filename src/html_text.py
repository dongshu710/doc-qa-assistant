"""纯标准库 HTML 取文本（零第三方依赖）。

为什么需要：客户发来的是网页存档、内部 Wiki 导出的是 .html，用户不会先转成 md。
用 `html.parser` 而不是正则剥标签，是因为正则剥嵌套标签必然出错
（`<div><p>x</p></div>` 用贪婪/非贪婪都有反例），而且会把 `<script>` 里的代码
当成正文塞进知识库。

能力边界：
- 支持：标题（h1–h3）、段落、列表、表格单元格（按行拼成 ` | `）、实体解码。
- 跳过：script / style / nav / footer / 表单控件（这些是「页面的壳」，不是内容）。
  侧边栏与页脚往往在每页重复，收进知识库会变成高频噪声，把真正的条款挤下去。
- 不保留：链接地址（只留链接文字）、图片（无 OCR）、CSS 布局含义。
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

TAG_BLOCK = {"p", "div", "section", "article", "header", "main", "br", "hr",
             "li", "tr", "table", "blockquote", "pre"}
TAG_SKIP = {"script", "style", "nav", "footer", "aside", "form", "noscript", "svg"}
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
MAX_CHARS = 400_000


class HtmlError(RuntimeError):
    pass


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []      # 已完成的段落（Markdown 行）
        self._buf: list[str] = []
        self._skip = 0
        self._heading = 0
        self._row: list[str] = []
        self._cell: list[str] = []
        self._in_cell = False
        self.rows = 0

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        self._buf = []
        if not text:
            return
        if self._heading:
            self.blocks.append("#" * self._heading + " " + text)
        else:
            self.blocks.append(text)

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in TAG_SKIP:
            self._skip += 1
            return
        if tag in HEADINGS:
            self._flush()
            self._heading = HEADINGS[tag]
        elif tag in TAG_BLOCK:
            self._flush()
        elif tag in ("td", "th"):
            self._cell = []
            self._in_cell = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in TAG_SKIP:
            self._skip = max(0, self._skip - 1)
            return
        # `tr` 必须排在 TAG_BLOCK 之前：它同时属于块级标签，
        # 先走块级分支的话整行永远拼不起来（表格只剩一格一格的行内文字）。
        if tag == "tr":
            if any(self._row):
                self.blocks.append(" | ".join(self._row))
                self.rows += 1
            self._row = []
            self._flush()
            return
        if tag in HEADINGS:
            self._flush()
            self._heading = 0
        elif tag in TAG_BLOCK:
            self._flush()
        elif tag in ("td", "th"):
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self._row.append(text)
            self._cell = []
            self._in_cell = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_cell:
            self._cell.append(data)
        else:
            self._buf.append(data)


def extract_html(data: bytes, title: str = "") -> tuple[str, dict]:
    """返回 (Markdown, 统计信息)。"""
    # 编码判定按「严格解码成不成功」而不是「替换符多不多」：
    # gb2312/gbk 页面按 utf-8 解，短页面只会产出十来个替换符，
    # 用比例阈值判断会漏掉它们（就是「小文件全乱码、大文件正常」这种怪现象）。
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("gb18030")
        except UnicodeDecodeError:
            # 两种都不是：留着替换符也要给出内容，并在 meta 里标出来
            text = data.decode("utf-8", errors="replace")
    collector = _Collector()
    try:
        collector.feed(text)
        collector.close()
    except Exception as exc:  # noqa: BLE001 —— 解析器内部错误也当成文件不可用
        raise HtmlError(f"HTML 解析失败：{type(exc).__name__}") from exc
    collector._flush()

    lines = [line for line in collector.blocks if line.strip()]
    if not lines:
        raise HtmlError("这个 HTML 里没有可提取的文字（可能是整页由脚本渲染）")
    used: list[str] = []
    total = 0
    for line in lines:
        if total + len(line) > MAX_CHARS:
            break
        used.append(line)
        total += len(line)
    md = f"# {title.strip() or '网页存档'}\n\n" + "\n\n".join(used) + "\n"
    return md, {
        "engine": "builtin-html",
        "blocks": len(used),
        "tables": collector.rows,
        "chars": total,
        # 解码失败留下的替换符数量：>0 说明这份文件按已知编码都解不干净，
        # 入库后会出现乱码词，调用方据此提示用户另存为 UTF-8。
        "bad_chars": md.count("\ufffd"),
        # 截断要说出来：用户以为整页都入库了，问后半部分却答不出，会去怀疑检索
        "truncated": len(used) < len(lines),
    }
