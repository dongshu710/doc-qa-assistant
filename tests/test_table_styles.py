"""xlsx 表格入库：单元格格式（百分比 / 日期 / 货币 / 千分位）与合并单元格。

这批用例的由来：金融场景里「3.5%」在 xlsx 内部是 0.035、日期是序列号 45678，
只读 `<v>` 会把这两类数字原样写进知识库——用户问「管理费率多少」，
答案给出 0.035 而不是 3.5%，**而且不报错**。读错比答不出危险，所以要有门禁。

同时守住三条边界：
1. 没有 styles.xml 的旧文件不能崩，退回原值并在 meta 里说明；
2. 1900 闰年 bug 那两个临界序列号（59/61）要各自正确；
3. 合并单元格要把左上角的值铺满，否则表头只剩一列有名字、整表错列。

不联网、不依赖 openpyxl：手写最小 xlsx（zip + XML）。
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import table_text  # noqa: E402

FAILED = 0
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def col(index: int) -> str:
    """0 → A，26 → AA。"""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def build_xlsx(rows, formats: list | None = None,
               merges: list[str] | None = None, sheet: str = "费率表") -> bytes:
    """rows 的每个单元格可以是 str，也可以是 (值, 样式下标)。

    样式下标对应 `formats` 的序号 + 1：0 号样式留给 General（无格式）。
    `formats` 里每项可以是格式码字符串（写进自定义 numFmts，id 从 164 起），
    也可以是内置 numFmtId（整数，比如 14 表示内置日期）。
    """
    xml_rows = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, cell in enumerate(row):
            if isinstance(cell, tuple):
                value, style = cell
            else:
                value, style = cell, None
            if value == "" or value is None:
                continue
            ref = f"{col(c)}{r}"
            attr = f' s="{style}"' if style else ""
            try:
                float(value)
                cells.append(f'<c r="{ref}"{attr}><v>{value}</v></c>')
            except (TypeError, ValueError):
                cells.append(f'<c r="{ref}"{attr} t="inlineStr"><is><t>{value}</t></is></c>')
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')

    merge_xml = ""
    if merges:
        items = "".join(f'<mergeCell ref="{ref}"/>' for ref in merges)
        merge_xml = f'<mergeCells count="{len(merges)}">{items}</mergeCells>'

    sheet_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{MAIN}">'
        f'<sheetData>{"".join(xml_rows)}</sheetData>{merge_xml}</worksheet>'
    )
    workbook_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{MAIN}" xmlns:r="{REL}">'
        f'<sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{PKG}">'
        f'<Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/>'
        f"</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/></Types>'
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", (
            f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{PKG}">'
            f'<Relationship Id="rId0" Type="{PKG}/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"))
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        if formats:
            custom = []
            xfs = ['<xf numFmtId="0"/>']
            for i, fmt in enumerate(formats):
                if isinstance(fmt, int):
                    xfs.append(f'<xf numFmtId="{fmt}" applyNumberFormat="1"/>')
                else:
                    num_id = 164 + i
                    # formatCode 常带引号（`"¥"#,##0.00`），必须转义进属性，
                    # 否则 styles.xml 直接坏掉——真实 xlsx 也是这么存的
                    escaped = (str(fmt).replace("&", "&amp;").replace("<", "&lt;")
                               .replace(">", "&gt;").replace('"', "&quot;"))
                    custom.append(f'<numFmt numFmtId="{num_id}" formatCode="{escaped}"/>')
                    xfs.append(f'<xf numFmtId="{num_id}" applyNumberFormat="1"/>')
            numfmts = (f'<numFmts count="{len(custom)}">{"".join(custom)}</numFmts>'
                       if custom else "")
            archive.writestr("xl/styles.xml", (
                f'<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="{MAIN}">'
                f'{numfmts}<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs></styleSheet>'))
    return buffer.getvalue()


def cell_at(markdown: str, row: int, col_index: int) -> str:
    """取 Markdown 表里的某格（跳过表头分隔行）。row 从 0 起，0 是表头。"""
    lines = [line for line in markdown.splitlines() if line.startswith("|")]
    if row + 1 >= len(lines):
        return ""
    cells = [part.strip() for part in lines[row + 1].strip("|").split("|")]
    return cells[col_index] if col_index < len(cells) else ""


def test_percent() -> None:
    print("百分比：0.035 + 0.00% → 3.50%")
    data = build_xlsx([["产品", "管理费率"], ["稳盈", ("0.035", 1)]], formats=["0.00%"])
    md, meta = table_text.extract_table(data, "费率.xlsx")
    check("管理费率渲染成 3.50%", cell_at(md, 1, 1) == "3.50%", cell_at(md, 1, 1))
    check("meta 说明已按格式渲染", "已按单元格格式渲染" in (meta.get("note") or ""),
          str(meta.get("note")))


def test_date() -> None:
    print("日期：序列号按内置格式 14 转成年月日")
    serial = 45678
    expected = (date(1899, 12, 30) + timedelta(days=serial)).strftime("%Y-%m-%d")

    plain = build_xlsx([["生效日"], [("45678", None)]])
    md_plain, _ = table_text.extract_table(plain, "日期.xlsx")
    check("没有样式的单元格保持序列号（不猜）",
          cell_at(md_plain, 1, 0) == "45678", cell_at(md_plain, 1, 0))

    built = build_xlsx([["生效日"], [("45678", 1)]], formats=[14])
    md, _ = table_text.extract_table(built, "日期2.xlsx")
    check(f"内置格式 14 渲染成 {expected}", cell_at(md, 1, 0) == expected, cell_at(md, 1, 0))


def test_builtin_date_ids() -> None:
    print("内置日期/时间格式 id 的归类")
    def kind(fmt_id: int) -> str:
        if fmt_id in table_text._TIME_FMT_IDS:
            return "time"
        if fmt_id in table_text._DATE_FMT_IDS:
            return "date"
        return "other"

    check("14 是日期", kind(14) == "date", kind(14))
    check("22 是日期时间（按日期处理）", kind(22) == "date", kind(22))
    check("18 与 45 是时间", kind(18) == "time" and kind(45) == "time",
          f"{kind(18)}/{kind(45)}")
    check("31 与 50 是地区日期", kind(31) == "date" and kind(50) == "date",
          f"{kind(31)}/{kind(50)}")
    check("9/10（百分比）没有被误判成日期", kind(9) == "other" and kind(10) == "other",
          f"{kind(9)}/{kind(10)}")


def test_currency_and_grouping() -> None:
    print("货币符号、千分位、负数括号")
    data = build_xlsx(
        [["金额", "笔数", "差额"],
         [("1234.5", 1), ("1234567", 2), ("-1234.5", 3)]],
        formats=['"¥"#,##0.00', "#,##0", "#,##0.00;(#,##0.00)"])
    md, _ = table_text.extract_table(data, "金额.xlsx")
    check("货币 1,234.50", cell_at(md, 1, 0) == "¥1,234.50", cell_at(md, 1, 0))
    check("千分位整数 1,234,567", cell_at(md, 1, 1) == "1,234,567", cell_at(md, 1, 1))
    check("负数用括号 (1,234.50)", cell_at(md, 1, 2) == "(1,234.50)", cell_at(md, 1, 2))


def test_merge() -> None:
    print("合并单元格：左上角的值铺满整个区域")
    data = build_xlsx(
        [["产品名称", "期限", "费率"],
         [("稳盈系列", None), ("90 天", 1), ("0.035", 1)]],
        formats=["0.00%"], merges=["A2:A3"])
    md, _ = table_text.extract_table(data, "合并.xlsx")
    check("第一行第二列拿到值", cell_at(md, 1, 0) == "稳盈系列", cell_at(md, 1, 0))
    # A2:A3 合并：只有 A2 有值，A3 由填充得到（本表只有两行数据，看行 2）

    data2 = build_xlsx(
        [["产品", "90 天", "180 天"],
         [("稳盈系列", None), ("0.03", 1), ("0.035", 1)],
         [("", None), ("0.031", 1), ("0.036", 1)]],
        formats=["0.00%"], merges=["A2:A3"])
    md2, _ = table_text.extract_table(data2, "合并2.xlsx")
    check("合并区域下方也铺上值", cell_at(md2, 2, 0) == "稳盈系列", cell_at(md2, 2, 0))
    check("铺值不影响其他列", cell_at(md2, 2, 1) == "3.10%", cell_at(md2, 2, 1))


def test_time_and_edge_dates() -> None:
    print("纯时间与 1900 闰年边界")
    check("59 → 1900-02-28",
          table_text._format_date(59, "yyyy-mm-dd") == "1900-02-28",
          table_text._format_date(59, "yyyy-mm-dd"))
    check("61 → 1900-03-01",
          table_text._format_date(61, "yyyy-mm-dd") == "1900-03-01",
          table_text._format_date(61, "yyyy-mm-dd"))
    check("1 → 1900-01-01",
          table_text._format_date(1, "yyyy-mm-dd") == "1900-01-01",
          table_text._format_date(1, "yyyy-mm-dd"))
    check("0.604166 → 14:30", table_text._format_date(0.6041666, "h:mm") == "14:30",
          table_text._format_date(0.6041666, "h:mm"))
    check("带秒的时间格式带秒", table_text._format_date(0.5, "hh:mm:ss") == "12:00:00",
          table_text._format_date(0.5, "hh:mm:ss"))
    check("明显不是日期的超大数返回空",
          table_text._format_date(99999999, "yyyy-mm-dd") == "",
          table_text._format_date(99999999, "yyyy-mm-dd"))


def test_without_styles() -> None:
    print("没有 styles.xml 的旧文件：不崩，退回原值")
    data = build_xlsx([["费率"], [("0.035", None)]])
    md, meta = table_text.extract_table(data, "旧文件.xlsx")
    check("值保持原样", cell_at(md, 1, 0) == "0.035", cell_at(md, 1, 0))
    check("meta 提示未读到样式", "未读到样式" in (meta.get("note") or ""), str(meta.get("note")))


def test_broken_styles() -> None:
    print("styles.xml 损坏：不让整张表读不出来")
    good = build_xlsx([["费率"], [("0.035", 1)]], formats=["0.00%"])
    # 把 styles.xml 替换成坏 XML
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(good)) as source, \
            zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename == "xl/styles.xml":
                payload = b"<styleSheet><numFmts>bad"
            target.writestr(item, payload)
    md, meta = table_text.extract_table(buffer.getvalue(), "坏样式.xlsx")
    check("仍然能读出表格", "费率" in md, md[:60])
    check("样式读不到就退回原值", cell_at(md, 1, 0) == "0.035", cell_at(md, 1, 0))


def test_text_format_untouched() -> None:
    print("文本格式 @ 不参与数字渲染")
    check("文本掩码原样返回", table_text._format_number("0.035", "@") == "0.035",
          table_text._format_number("0.035", "@"))
    check("General 原样返回", table_text._format_number("0.035", "") == "0.035",
          table_text._format_number("0.035", ""))
    check("非数字值原样返回", table_text._format_number("稳盈", "0.00%") == "稳盈",
          table_text._format_number("稳盈", "0.00%"))


def main() -> int:
    test_percent()
    test_date()
    test_builtin_date_ids()
    test_currency_and_grouping()
    test_merge()
    test_time_and_edge_dates()
    test_without_styles()
    test_broken_styles()
    test_text_format_untouched()
    print()
    if FAILED:
        print(f"TABLE STYLES FAILED: {FAILED}")
        return 1
    print("TABLE STYLES OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
