"""表格入库：xlsx / csv / tsv → Markdown。

为什么自己解 xlsx：
项目承诺零第三方依赖（requirements 里 openpyxl 一直是注释状态），而 xlsx 本质是
zip + XML，读 sharedStrings、styles、worksheet 三个部件就够把单元格**显示值**取出来。

样式这一层是 1.35.0 补的，起因是金融场景下的静默错误：
xlsx 把「3.5%」存成 0.035、把日期存成序列号 45678，只读 `<v>` 等于把这些数字
原样塞进知识库——用户问「管理费率是多少」，答案会给出 0.035 而不是 3.5%，
而且**不会报错**。读错比答不出更危险。

现在支持（按 numFmt 格式码判断，不猜）：
- 百分比：`0.00%` → `3.50%`
- 千分位与定点小数：`#,##0.00` → `1,234.50`
- 货币：格式码里带 ¥ / $ / € / £（含 `[¥-804]` 这种区域写法）→ `¥1,234.50`
- 日期与时间：内置格式 14–22 / 27–36 / 45–47 / 50–58，以及自定义格式里的 y/d/h/s
- 负数括号写法 `(0.00)` → `(1,234.50)`
- 合并单元格：把左上角的值铺满整个区域，否则右侧与下方是空串，列会整体错位

仍然不做（写清楚，不假装支持）：
- 不还原公式，只取缓存的计算结果；
- 不处理条件格式、颜色、字体；
- 自定义格式里的条件段（`[>100]0;0`）只按第一段渲染；
- 数字格式里的科学计数法按普通小数渲染。
"""
from __future__ import annotations

import csv
import io
import math
import posixpath
import re
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

from . import zipguard

TABLE_EXT = (".xlsx", ".csv", ".tsv")
MAX_ROWS = 2000          # 单表最多取多少行：再多也不适合塞进上下文
MAX_COLS = 60            # 超宽表只取前 60 列，并在 meta 里标注

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_CELL_REF = re.compile("([A-Z]+)([0-9]+)?")
_SPACES = re.compile(" {2,}")

# Excel 内置数字格式里属于「日期/时间」的那些 id（ECMA-376 第 18.8.30 节）。
# 不走「小于 163 就算内置」这种简化：163 以内还有 0/2/4/9/10 这些纯数字格式。
_DATE_FMT_IDS = frozenset(
    list(range(14, 18)) + [22] + list(range(27, 37)) + list(range(50, 59)))
_TIME_FMT_IDS = frozenset({18, 19, 20, 21, 45, 46, 47})
# 内置的日期/时间格式没有 formatCode，用一个等价占位让下游知道该走日期分支
_DATE_PLACEHOLDER = "yyyy-mm-dd"
_TIME_PLACEHOLDER = "hh:mm:ss"
# 内置格式码：只登记我们会渲染的那几个，其余按 General 处理（原样输出）。
_BUILTIN_FMT = {
    9: "0%", 10: "0.00%",
    2: "0.00",
    3: "#,##0", 4: "#,##0.00",
    37: "#,##0 ;(#,##0)", 38: "#,##0 ;[Red](#,##0)",
    39: "#,##0.00;(#,##0.00)", 40: "#,##0.00;[Red](#,##0.00)",
}
_CURRENCY_SYMBOLS = ("¥", "￥", "$", "€", "£", "₩", "₹", "₽")
# `[$¥-804]` 这类区域标记：方括号里带符号就是货币，带 `$-` 只是语言代码，不能当货币
_LOCALE_MARK = re.compile(r"\[\$([^\]\-]*)-[0-9A-Fa-f]{2,8}\]")


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


def _styles(archive: zipfile.ZipFile) -> list[str]:
    """返回「样式索引 → 格式码」。

    单元格的 `s` 属性是 `cellXfs` 的下标，不是 numFmtId；中间还隔着一张
    `numFmts` 自定义格式表。少跳这一层，就会把「3.5%」当成 0.035 直接入库。
    """
    try:
        raw = archive.read("xl/styles.xml")
    except KeyError:
        return []          # 没有样式部件：所有单元格按 General 处理
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []          # 样式坏了不该让整张表都读不出来
    custom: dict[int, str] = {}
    node = root.find(f"{_MAIN}numFmts")
    if node is not None:
        for item in node.findall(f"{_MAIN}numFmt"):
            try:
                fmt_id = int(item.get("numFmtId") or "")
            except ValueError:
                continue
            custom[fmt_id] = item.get("formatCode") or ""
    out: list[str] = []
    xfs = root.find(f"{_MAIN}cellXfs")
    if xfs is not None:
        for xf in xfs.findall(f"{_MAIN}xf"):
            try:
                fmt_id = int(xf.get("numFmtId") or 0)
            except ValueError:
                fmt_id = 0
            if fmt_id in custom:
                out.append(custom[fmt_id])
            elif fmt_id in _TIME_FMT_IDS:
                out.append(_TIME_PLACEHOLDER)
            elif fmt_id in _DATE_FMT_IDS:
                out.append(_DATE_PLACEHOLDER)
            else:
                out.append(_BUILTIN_FMT.get(fmt_id, ""))
    return out


def _mask(fmt: str) -> str:
    """取出数字掩码：去掉引号里的文字、方括号标记、转义符与条件段。

    只看第一段（`;` 之前）：`0.00;(0.00)` 的负数段由 `_format_number` 单独处理，
    这里只需要知道「有几个小数位、要不要千分位」。
    """
    section = fmt.split(";")[0]
    section = re.sub(r'"[^"]*"', "", section)
    section = re.sub(r"\[[^\]]*\]", "", section)
    return section.replace("\\", "").strip()


def _decimals(mask: str) -> int:
    match = re.search(r"\.([0#]+)", mask)
    return len(match.group(1)) if match else 0


def _is_date_mask(mask: str) -> bool:
    low = mask.lower()
    if not low or "%" in low:
        return False
    if re.search(r"[yd]", low):
        return True
    # 只有 `h:mm` / `mm:ss` 这种纯时间也算日期格式（序列号是「一天中的比例」）
    return ":" in low and bool(re.search(r"[hs]", low))


def _currency_symbol(fmt: str) -> str:
    # `[$¥-804]` 里的 ¥ 是货币；`[$-409]` 里的 `$-` 只是语言代码，不能当货币
    for match in _LOCALE_MARK.finditer(fmt):
        symbol = (match.group(1) or "").strip()
        if symbol:
            return symbol
    cleaned = _LOCALE_MARK.sub("", fmt)
    for symbol in _CURRENCY_SYMBOLS:
        if symbol in cleaned:
            return symbol
    return ""


def _format_date(serial: float, mask: str) -> str:
    """Excel 序列号 → 人能读的日期/时间。失败返回空串，由调用方退回原值。"""
    low = mask.lower()
    has_date = bool(re.search(r"[yd]", low))
    has_time = ":" in low and bool(re.search(r"[hs]", low))
    days = int(math.floor(serial))
    frac = serial - days
    if days < 0 or days > 2958465:       # Excel 上限 9999-12-31，超出多半不是日期
        return ""
    if has_date:
        # 1900 系统把 1900 当成闰年（序列号 60 是不存在的 2/29），
        # 所以 59 及以前用 12/31 做基准，60 及以后用 12/30，两条都对得上。
        base = date(1899, 12, 31) if days < 60 else date(1899, 12, 30)
        try:
            moment = datetime(base.year, base.month, base.day) + timedelta(days=days)
        except (OverflowError, ValueError):
            return ""
        if has_time:
            try:
                moment += timedelta(seconds=int(round(frac * 86400)))
            except OverflowError:
                return ""
            return moment.strftime("%Y-%m-%d %H:%M")
        return moment.strftime("%Y-%m-%d")
    if has_time:
        total = int(round(frac * 86400)) % 86400
        text = f"{total // 3600:02d}:{total % 3600 // 60:02d}"
        return text + (f":{total % 60:02d}" if "s" in low else "")
    return ""


def _format_number(raw: str, fmt: str) -> str:
    """按格式码把一个数字单元格渲染成「显示值」。"""
    text = (raw or "").strip()
    if not text or not fmt:
        return text
    try:
        number = float(text)
    except ValueError:
        return text              # 不是数字（极少见），原样返回
    mask = _mask(fmt)
    if not mask:
        return text
    if _is_date_mask(mask):
        rendered = _format_date(number, mask)
        return rendered or text
    if "%" in mask:
        return f"{number * 100:.{_decimals(mask)}f}%"
    if not re.search(r"[0#?]", mask):
        return text              # 纯文本格式（`@`）：不做数字渲染
    symbol = _currency_symbol(fmt)
    decimals = _decimals(mask)
    grouped = "," in mask
    body = f"{abs(number):,.{decimals}f}" if grouped else f"{abs(number):.{decimals}f}"
    if number < 0:
        # 会计格式用括号表示负数：`#,##0.00;(#,##0.00)`
        return f"({body})" if "(" in fmt else f"-{body}"
    return f"{symbol}{body}" if symbol else body


def _cell_text(cell, shared: list[str], styles: list[str]) -> str:
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
    if kind in (None, "n") and styles:
        try:
            fmt = styles[int(cell.get("s") or 0)]
        except (ValueError, IndexError):
            fmt = ""
        if fmt:
            return _clean(_format_number(value, fmt))
    return _clean(value)


def _cell_pos(ref: str) -> tuple[int, int] | None:
    """`C12` → (12, 2)。行号缺失或不是合法引用就返回 None。"""
    match = _CELL_REF.match((ref or "").upper())
    if not match or not match.group(2):
        return None
    column = 0
    for char in match.group(1):
        column = column * 26 + (ord(char) - 64)
    return int(match.group(2)), column - 1


def _merges(root) -> list[tuple[int, int, int, int]]:
    """合并区域 `A1:C1` → (起始行, 起始列, 结束行, 结束列)。"""
    out: list[tuple[int, int, int, int]] = []
    node = root.find(f"{_MAIN}mergeCells")
    if node is None:
        return out
    for item in node.findall(f"{_MAIN}mergeCell"):
        ref = item.get("ref") or ""
        if ":" not in ref:
            continue
        left, right = ref.split(":", 1)
        start, end = _cell_pos(left), _cell_pos(right)
        if start and end:
            out.append((start[0], start[1], end[0], end[1]))
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


def _sheet_rows(raw: bytes, shared: list[str], styles: list[str],
                max_rows: int, max_cols: int) -> list[list[str]]:
    root = ET.fromstring(raw)
    data = root.find(f"{_MAIN}sheetData")
    if data is None:
        return []

    # 按「绝对行号」收集：合并区域用的是绝对引用（A1:C1），
    # 只按出现顺序拍扁会让跨行合并在中间有空行时整体错位。
    by_row: dict[int, dict[int, str]] = {}
    order: list[int] = []
    seen = 0
    for row in data.findall(f"{_MAIN}row"):
        declared = row.get("r")
        row_no = int(declared) if declared and declared.isdigit() else seen + 1
        seen = row_no
        cells: dict[int, str] = {}
        for cell in row.findall(f"{_MAIN}c"):
            index = _col_index(cell.get("r") or "")
            if index is None or index >= max_cols:
                continue
            text = _cell_text(cell, shared, styles)
            if text:
                cells[index] = text
        if cells:
            by_row[row_no] = cells
            order.append(row_no)

    # 合并单元格：左上角的值铺满整个区域。不铺的话右侧与下方都是空串，
    # 「产品名称」只在第一列出现一次，转成 Markdown 后整张表错列——
    # 这比丢格式更难发现：表格看起来完整，只是每一行的含义都错了。
    for start_row, start_col, end_row, end_col in _merges(root):
        value = by_row.get(start_row, {}).get(start_col)
        if not value:
            continue
        for row_no in range(start_row, min(end_row, start_row + max_rows) + 1):
            if row_no not in order:
                order.append(row_no)
            target = by_row.setdefault(row_no, {})
            for col in range(start_col, min(end_col, max_cols - 1) + 1):
                target.setdefault(col, value)

    rows: list[list[str]] = []
    for row_no in sorted(order)[:max_rows]:
        cells = by_row.get(row_no) or {}
        width = max(cells) + 1 if cells else 0
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
                # 同 docx：先卡解压体积，再读条目
                try:
                    zipguard.guard(archive)
                except zipguard.ZipLimitError as exc:
                    raise TableError(str(exc)) from exc
                shared = _shared_strings(archive)
                styles = _styles(archive)
                parts = _sheet_parts(archive)
                sections: list[tuple[str, list[list[str]]]] = []
                for name, path in parts:
                    try:
                        raw = archive.read(path)
                    except KeyError:
                        continue
                    rows = [row for row in _sheet_rows(raw, shared, styles, max_rows, max_cols)
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
            "note": ("已按单元格格式渲染百分比 / 日期 / 货币；合并单元格把左上角的值铺满整个区域。"
                     "公式只取缓存值，不重新计算。") if styles else
                    ("未读到样式部件：日期可能显示为序列号，百分比可能显示为小数。"
                     "若表格来自 WPS 或非常规导出，请另存为 CSV 后重试。"),
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
