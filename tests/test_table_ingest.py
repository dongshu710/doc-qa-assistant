"""表格入库：xlsx / csv / tsv → Markdown，并验证生成的 Markdown 能被切分与关键词识别。

xlsx 夹具用 zipfile 手写：这既是测试，也是对「零第三方依赖解析」的验证——
如果解析器偷懒依赖了某个库，这个测试会直接失败。
"""
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def _col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def build_xlsx(rows: list[list[str]], sheet: str = "产品要素") -> bytes:
    """把二维字符串数组写成最小可用的 xlsx（共享字符串 + 一个工作表）。"""
    shared: list[str] = []
    index: dict[str, int] = {}
    xml_rows = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, value in enumerate(row):
            if value == "":
                continue
            if value not in index:
                index[value] = len(shared)
                shared.append(value)
            ref = f"{_col(c)}{r}"
            cells.append(f'<c r="{ref}" t="s"><v>{index[value]}</v></c>')
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')

    sheet_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{MAIN}">'
        f'<sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
    )
    shared_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="{MAIN}" count="{len(shared)}" '
        f'uniqueCount="{len(shared)}">'
        + "".join(f"<si><t>{value}</t></si>" for value in shared)
        + "</sst>"
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
        '<Default Extension="xml" ContentType="application/xml"/>'
        "</Types>"
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
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


def main() -> None:
    from src import ingest, table_text

    # ---------- 1) xlsx：表头 + 数据 + 竖线转义 ----------
    data = build_xlsx([
        ["产品名称", "起购金额", "风险等级"],
        ["稳盈 90 天", "1 元", "R2"],
        ["稳盈 180 天", "10 万元", "R3（含 | 双录）"],
    ])
    md, meta = table_text.extract_table(data, "产品要素.xlsx")
    assert meta["format"] == "xlsx" and meta["rows"] == 3, meta
    assert meta["sheets"] == ["产品要素"], meta
    assert "| 产品名称 | 起购金额 | 风险等级 |" in md, md
    assert "稳盈 90 天" in md and "10 万元" in md, md
    assert "含 \\| 双录" in md, "竖线必须转义成 \\|，否则表结构会被撑坏"
    row = next(line for line in md.splitlines() if "稳盈 180 天" in line)
    assert len(row.strip("|").split(" | ")) == 3, row   # 转义后仍是 3 列
    print("xlsx -> markdown OK，rows=%d" % meta["rows"])

    # ---------- 2) csv：GBK 编码 + 分号分隔 ----------
    gbk = "产品;起购金额\n稳盈 30 天;1000 元\n".encode("gb18030")
    md2, meta2 = table_text.extract_table(gbk, "要素.csv")
    assert meta2["format"] == "csv" and "稳盈 30 天" in md2, (meta2, md2)
    print("csv(GB18030) -> markdown OK")

    # ---------- 3) tsv ----------
    md3, _ = table_text.extract_table("产品\t期限\n稳盈\t90 天\n".encode("utf-8"), "a.tsv")
    assert "| 稳盈 | 90 天 |" in md3, md3
    print("tsv -> markdown OK")

    # ---------- 4) ingest_bytes 落盘 ----------
    tmp = tempfile.mkdtemp(prefix="table_ingest_")
    res = ingest.ingest_bytes(data, "产品要素.xlsx", tmp)
    assert res["ok"], res
    assert res["md"].endswith(".md") and os.path.exists(os.path.join(tmp, res["md"])), res
    assert res["format"] == "xlsx" and res["rows"] == 3, res
    assert "日期" in (res.get("note") or ""), res.get("note")
    print("ingest_bytes OK ->", res["md"], res["chars"], "chars")

    # ---------- 5) 生成的 Markdown 能被切分，且关键词能抽到 ----------
    from src.chunking import load_corpus
    from src.config import load_settings
    from src.keywords import KeywordIndex

    corpus_dir = tempfile.mkdtemp(prefix="table_corpus_")
    with open(os.path.join(corpus_dir, res["md"]), "w", encoding="utf-8") as f:
        f.write(Path(tmp, res["md"]).read_text(encoding="utf-8"))

    chunks = load_corpus(corpus_dir)
    assert chunks, "表格 Markdown 应能切出知识块"
    joined = "\n".join(chunk.text for chunk in chunks)
    assert "稳盈 90 天" in joined and "起购金额" in joined, joined[:300]

    os.environ["KEYWORD_INDEX"] = os.path.join(tempfile.mkdtemp(), "kw.json")
    index = KeywordIndex(chunks, load_settings())
    index.ensure(enrich=False)
    terms = {entry.term for entry in index.entries}
    assert "起购金额" in terms, sorted(terms)
    hit = index.match_report("稳盈 90 天的起购金额是多少")
    assert hit.hits, "表格表头应能作为关键词命中"
    print("table markdown -> chunks=%d, keyword hit=%s" % (len(chunks), hit.hits[0].entry.term))

    # ---------- 6) 失败路径必须说清楚 ----------
    try:
        table_text.extract_table(b"not a zip", "x.xlsx")
        raise AssertionError("坏 xlsx 应抛 TableError")
    except table_text.TableError as exc:
        assert "xlsx" in str(exc)
    blank = ingest.ingest_bytes(b"", "空.csv", tmp)
    assert not blank["ok"] and "空" in blank["error"], blank
    empty = ingest.ingest_bytes(b"a,b\n", "只有表头.csv", tmp)
    assert not empty["ok"] and "数据行" in empty["error"], empty
    print("failure paths OK")

    # ---------- 7) 扫描件提示必须是可操作的 ----------
    from src.pdf_ingest import assess
    hint = assess("", pages=3)
    assert hint and "OCR" in hint and "另存为" in hint, hint
    print("scan hint OK ->", hint[:40] + "…")

    print("TABLE INGEST OK")


if __name__ == "__main__":
    main()
