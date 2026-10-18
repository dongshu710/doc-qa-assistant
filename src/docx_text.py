"""纯标准库 DOCX 取文本（零第三方依赖）。

DOCX 本质是一个 ZIP，正文在 `word/document.xml`。这里按文档顺序遍历段落与表格，
用段落样式（Heading1 / 标题 1）还原 Markdown 标题——切分器就是按标题切块的，
标题还原得准，召回才准。

能力边界：
- 支持：标题、正文段落、软换行、制表符、表格（转 Markdown 表）、列表项（`- `）。
- 不支持：图片 OCR、批注、页眉页脚（不参与正文检索）、.doc 老格式、加密文档。
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocxError(RuntimeError):
    pass


def _tag(node) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _heading_level(style: str | None) -> int:
    """把段落样式名映射成标题级别：Heading1 / 标题 1 / 1 → 1，正文 → 0。"""
    s = (style or "").strip()
    if not s:
        return 0
    m = re.search(r"(?:heading|标题)\s*([1-6])", s, re.I)
    if m:
        return int(m.group(1))
    if s.lower() in ("title", "标题"):
        return 1
    if s in {"1", "2", "3", "4", "5", "6"}:
        return int(s)
    return 0


def _paragraph(node) -> tuple[str, int, bool]:
    """返回 (文本, 标题级别, 是否列表项)。"""
    level = 0
    is_list = False
    for child in node.iter():
        name = _tag(child)
        if name == "pStyle":
            level = _heading_level(child.get(_W + "val"))
        elif name == "numPr":
            is_list = True
        elif name == "outlineLvl":  # 部分模板用大纲级别而不是样式
            try:
                lvl = int(child.get(_W + "val") or -1)
                if 0 <= lvl <= 5 and not level:
                    level = lvl + 1
            except ValueError:
                pass

    parts: list[str] = []
    for child in node.iter():
        name = _tag(child)
        if name == "t":
            parts.append(child.text or "")
        elif name == "tab":
            parts.append("\t")
        elif name in ("br", "cr"):
            parts.append("\n")
    return "".join(parts).strip(), level, is_list


def _table_rows(node) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in node.findall(f"{_W}tr"):
        cells: list[str] = []
        for tc in tr.findall(f"{_W}tc"):
            texts = [t for t, _lvl, _li in (_paragraph(p) for p in tc.findall(f"{_W}p")) if t]
            cells.append(" ".join(texts).strip())
        if any(cells):
            rows.append(cells)
    return rows


def _table_markdown(rows: list[list[str]]) -> list[str]:
    """单行表格退化为一行文本；多行表格转 Markdown 表（保住列结构）。"""
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    if len(rows) == 1:
        return [" | ".join(rows[0])]
    out = ["| " + " | ".join(rows[0]) + " |",
           "| " + " | ".join(["---"] * width) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return out


def extract_docx(data: bytes, title: str | None = None) -> tuple[str, dict]:
    """从 .docx 字节流还原 Markdown。返回 (markdown, 统计信息)。"""
    if not data.startswith(b"PK"):
        raise DocxError("不是有效的 .docx（ZIP 头缺失）；.doc 老格式请先另存为 .docx")

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocxError(f"DOCX 解压失败：{exc}") from exc

    names = set(zf.namelist())
    if "word/document.xml" not in names:
        raise DocxError("不是有效的 Word 文档（缺少 word/document.xml）")
    if any(n.lower().startswith("encryptedpackage") for n in names):
        raise DocxError("文档已加密，暂不支持（请先取消密码保护）")

    try:
        root = ET.fromstring(zf.read("word/document.xml"))
    except ET.ParseError as exc:
        raise DocxError(f"document.xml 解析失败：{exc}") from exc

    body = root.find(f"{_W}body")
    if body is None:
        raise DocxError("文档结构异常（缺少 w:body）")

    items: list[tuple[str, int, str]] = []  # (类型, 标题级别, 文本)
    paragraphs = tables = headings = 0

    for child in list(body):
        name = _tag(child)
        if name == "p":
            text, level, is_list = _paragraph(child)
            if not text:
                continue
            paragraphs += 1
            if level:
                headings += 1
                items.append(("h", level, text))
            elif is_list:
                items.append(("li", 0, text))
            else:
                items.append(("p", 0, text))
        elif name == "tbl":
            rows = _table_rows(child)
            if rows:
                tables += 1
                # 表格必须整块输出：行与行之间隔空行就不再是 Markdown 表
                items.append(("md", 0, "\n".join(_table_markdown(rows))))

    if not items:
        raise DocxError("文档里没有可提取的文字（可能全是图片或文本框）")

    # 文档若以一级标题开头，就用它当主标题；否则补一个 `# 文件名` 并把标题整体降一级
    shift = 0 if (items[0][0] == "h" and items[0][1] == 1) else 1
    blocks: list[str] = []
    for kind, level, text in items:
        if kind == "h":
            blocks.append("#" * min(6, level + shift) + " " + text)
        elif kind == "li":
            blocks.append("- " + text)
        else:
            blocks.append(text)

    header = f"# {title}\n\n" if (shift and title) else ""
    md = header + "\n\n".join(blocks) + "\n"
    text_chars = len(re.sub(r"\s", "", "".join(blocks)))
    return md, {
        "engine": "builtin-docx",
        "paragraphs": paragraphs,
        "tables": tables,
        "headings": headings,
        "chars": text_chars,
    }
