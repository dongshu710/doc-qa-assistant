"""表格入库：xlsx / csv / tsv → Markdown。

为什么自己解 xlsx：
项目承诺零第三方依赖（requirements 里 openpyxl 一直是注释状态），而 xlsx 本质是
zip + XML，读 sharedStrings 与 worksheet 两个部件就够把单元格文字取出来。

代价必须说清楚，不假装支持：
- **不解析样式**：日期单元格会变成序列号（如 45678），百分比/货币格式丢失；
- **合并单元格**只在左上角有值，其余为空；
- 只取单元格的显示文本，不还原公式。
这三点对「产品要素表 / 价目表 / 额度表」够用（它们本来就是文字与数字），
对「以日期为核心的排期表」不够，需要在源文件里把日期转成文本再上传。
"""
from __future__ import annotations

import csv
import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

TABLE_EXT = (".xlsx", ".csv", ".tsv")
MAX_ROWS = 2000          # 单表最多取多少行：再多也不适合塞进上下文
MAX_COLS = 60            # 超宽表只取前 60 列，并在 meta 里标注

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_CELL_REF = re.compile("([A-Z]+)([0-9]+)?")
_SPACES = re.compile(" {2,}")


class TableError(RuntimeError):
    """表格解析失败（文件损坏、编码无法识别、内容为空）。"""


def _col_index(ref: str) -> int | None:
    """把 `C12` 里的 `C` 换成 0 基列号；无法识别返回 None。"""
    match = _CELL_REF.match((ref or "").upper())
    if not match:
        return None
    index = 0
    for char in match.group(1):
        index = index * 26 + (ord(char) - 64)
    return index - 1


def _clean(value: str) -> str:
    """单元格文本：换行折成空格、压缩连续空格、去掉首尾空白。"""
    text = (value or "").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return _SPACES.sub(" ", text).strip()


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    """共享字符串表：xlsx 把重复文本放这里，单元格只存下标。"""
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    out: list[str] = []
    for item in root.findall(f"{_MAIN}si"):
        # 富文本会被拆成多个 <r><t>，要拼起来才是完整单元格
        out.append("".join(node.text or "" for node in item.iter(f"{_MAIN}t")))
    return out


def _sheet_parts(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    """工作表名 → zip 内部路径。"""
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except KeyError as exc:
        raise TableError("不是有效的 .xlsx（缺少 workbook 部件）") from exc

    targets = {}
    for rel in rels:
        rid = rel.get("Id")
        target = rel.get("Target")
        if rid and target:
            targets[rid] = target

    parts: list[tuple[str, str]] = []
    sheets = workbook.find(f"{_MAIN}sheets")
    if sheets is None:
        return parts
    for sheet in sheets:
        name = sheet.get("name") or f"Sheet{len(parts) + 1}"
        rid = sheet.get(f"{_REL}id")
        target = targets.get(rid or "", "")
        if not target:
            continue
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = posixpath.normpath(posixpath.join("xl", target))
        parts.append((name, path))
    return parts


def _cell_text(cell, shared: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        node = cell.find(f"{_MAIN}is")
        if node is None:
            return ""
        return _clean("".join(part.text or "" for part in node.iter(f"{_MAIN}t")))
    node = cell.find(f"{_MAIN}v")
    if node is None or node.text is None:
        return ""
    value = node.text
    if kind == "s":
        try:
            return _clean(shared[int(value)])
        except (ValueError, IndexError):
            return ""
    if kind == "b":
        return "是" if value.strip() == "1" else "否"
    if kind == "e":
        return ""
    return _clean(value)


def _sheet_rows(raw: bytes, shared: list[str],
                max_rows: int, max_cols: int) -> list[list[str]]:
    root = ET.fromstring(raw)
    data = root.find(f"{_MAIN}sheetData")
    if data is None:
        return []

    rows: list[list[str]] = []
    for row in data.findall(f"{_MAIN}row"):
        if len(rows) >= max_rows:
            break
        cells: dict[int, str] = {}
        for cell in row.findall(f"{_MAIN}c"):
            index = _col_index(cell.get("r") or "")
            if index is None or index >= max_cols:
                continue
            text = _cell_text(cell, shared)
            if text:
                cells[index] = text
        if not cells:
            rows.append([])
            continue
        width = max(cells) + 1
        rows.append([cells.get(i, "") for i in range(width)])
    return rows


def _markdown(title: str, sections: list[tuple[str, list[list[str]]]]) -> str:
    lines = [f"# {title}", ""]
    for name, rows in sections:
        rows = [row for row in rows if any(cell for cell in row)]
        if not rows:
            continue
        width = max(len(row) for row in rows)
        width = max(1, width)
        lines.append(f"## {name}")
        lines.append("")
        header = rows[0] + [""] * (width - len(rows[0]))
        header = [cell or f"列{i + 1}" for i, cell in enumerate(header)]
        lines.append("| " + " | ".join(_escape(cell) for cell in header) + " |")
        lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
        for row in rows[1:]:
            cells = row + [""] * (width - len(row))
            lines.append("| " + " | ".join(_escape(cell) for cell in cells) + " |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _escape(cell: str) -> str:
    """表格单元格里的竖线会把 Markdown 表结构撑坏，必须转义。"""
    return cell.replace("|", "\\|")


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise TableError("无法识别文件编码（试过 UTF-8 / GB18030），请另存为 UTF-8 后重试")


def _csv_rows(text: str, dialect, max_rows: int, max_cols: int) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text), dialect)
    rows: list[list[str]] = []
    for row in reader:
        if len(rows) >= max_rows:
            break
        rows.append([_clean(cell) for cell in row[:max_cols]])
    return rows


def _csv_dialect(text: str, suffix: str):
    if suffix == ".tsv":
        return csv.excel_tab
    sample = text[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel      # 单列或格式不规整时退回逗号，交给后续校验


def extract_table(data: bytes, filename: str,
                  max_rows: int = MAX_ROWS, max_cols: int = MAX_COLS) -> tuple[str, dict]:
    """把 xlsx / csv / tsv 的字节流变成 Markdown。返回 (markdown, meta)。"""
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    title = filename.rsplit(".", 1)[0] or "表格"

    if suffix == ".xlsx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                shared = _shared_strings(archive)
                parts = _sheet_parts(archive)
                sections: list[tuple[str, list[list[str]]]] = []
                for name, path in parts:
                    try:
                        raw = archive.read(path)
                    except KeyError:
                        continue
                    rows = [row for row in _sheet_rows(raw, shared, max_rows, max_cols)
                            if any(cell for cell in row)]
                    # 只有表头没有数据的工作表不入库：切出来也答不了任何问题
                    if len(rows) >= 2:
                        sections.append((name, rows))
        except zipfile.BadZipFile as exc:
            raise TableError("不是有效的 .xlsx（ZIP 结构损坏）；.xls 老格式请先另存为 .xlsx") from exc
        except ET.ParseError as exc:
            raise TableError(f".xlsx 内部 XML 解析失败：{exc}") from exc
        if not sections:
            raise TableError("这个工作簿里没有可用内容（工作表为空，或只有表头没有数据行）")
        meta = {
            "format": "xlsx",
            "engine": "stdlib-zip+xml",
            "sheets": [name for name, _ in sections],
            "rows": sum(len(rows) for _, rows in sections),
            "truncated": any(len(rows) >= max_rows for _, rows in sections),
            "note": "未解析单元格样式：日期显示为序列号、合并单元格只在左上角有值；"
                    "需要精确保留格式时请另存为 CSV。",
        }
        return _markdown(title, sections), meta

    if suffix in (".csv", ".tsv"):
        text = _decode(data)
        if not text.strip():
            raise TableError("文件是空的")
        dialect = _csv_dialect(text, suffix)
        rows = [row for row in _csv_rows(text, dialect, max_rows, max_cols)
                if any(cell for cell in row)]
        if not rows:
            raise TableError("没有解析到任何单元格，请确认分隔符与编码")
        if len(rows) < 2:
            raise TableError("只有表头，没有数据行；请确认文件没有被截断")
        width = max(len(row) for row in rows)
        meta = {
            "format": suffix.lstrip("."),
            "engine": "stdlib-csv",
            "sheets": ["数据"],
            "rows": len(rows),
            "cols": width,
            "truncated": len(rows) >= max_rows,
            "note": None,
        }
        return _markdown(title, [("数据", rows)]), meta

    raise TableError(f"不支持的表格格式 {suffix or '（无扩展名）'}，只接受 .xlsx / .csv / .tsv")
