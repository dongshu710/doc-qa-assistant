"""生成 PDF 上传测试用的固定样本（用 .venv 跑一次即可，产物已入库）。

  .venv/Scripts/python.exe tests/fixtures/build_fixtures.py

三个样本：
- `sample_text.pdf`：有文本层，含一个只有它才有的数字（用于验证「上传后真能答」）
- `sample_scanned.pdf`：只有页面、没有文本层，模拟扫描件（用于验证质量闸门）
- `sample_doc.docx`：两级标题 + 正文 + 表格（用于验证 DOCX 解析与自动出题）
"""
import os
import zipfile
from xml.sax.saxutils import escape


FONT = r"C:\Windows\Fonts\simhei.ttf"
HERE = os.path.dirname(os.path.abspath(__file__))


def _pdf():
    from fpdf import FPDF  # 仅生成 PDF 样本时需要

    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("hei", "", FONT)
    pdf.set_font("hei", size=16)
    return pdf


def build_text() -> None:
    pdf = _pdf()
    pdf.multi_cell(0, 10, "云杉计划经费管理办法（测试样本）")
    pdf.ln(2)
    pdf.set_font("hei", size=11)
    for line in [
        "一、适用范围",
        "本办法适用于云杉计划全体参与人员的差旅、采购与外部服务支出。",
        "二、年度额度",
        "云杉计划每人每年差旅报销上限为 8.7 万元，超出部分需报预算委员会单独审批。",
        "三、审批时限",
        "报销单提交后，财务共享中心应在 3 个工作日内完成初审。",
        "四、特殊条款",
        "涉及跨境差旅的，需提前 10 个工作日提交备案，并附行程与预算明细。",
    ]:
        pdf.multi_cell(0, 7, line)
        pdf.ln(1)
    pdf.output(os.path.join(HERE, "sample_text.pdf"))


def build_scanned() -> None:
    """只有一页空白（无文本层），用来触发「疑似扫描件」告警。"""
    pdf = _pdf()
    pdf.rect(20, 20, 100, 40)
    pdf.output(os.path.join(HERE, "sample_scanned.pdf"))


def _docx_xml(blocks) -> str:
    """把块列表渲染成 document.xml（w:p / w:tbl）。"""
    body = []
    for kind, value in blocks:
        if kind == "table":
            rows = []
            for row in value:
                cells = "".join(
                    '<w:tc><w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p></w:tc>' % escape(c)
                    for c in row
                )
                rows.append("<w:tr>%s</w:tr>" % cells)
            body.append("<w:tbl>%s</w:tbl>" % "".join(rows))
            continue
        style = {"h1": "Heading1", "h2": "Heading2"}.get(kind)
        ppr = '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % style if style else ""
        body.append(
            '<w:p>%s<w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % (ppr, escape(value))
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>%s<w:sectPr/></w:body></w:document>" % "".join(body)
    )


def build_docx() -> None:
    """生成一份可解析的 .docx：两级标题 + 正文 + 表格。"""
    blocks = [
        ("h1", "银杏计划采购管理办法（测试样本）"),
        ("h2", "一、适用范围"),
        ("p", "本办法适用于银杏计划下所有采购活动，包括货物、服务与工程类采购。"),
        ("h2", "二、审批额度"),
        ("p", "单笔采购金额超过 12.6 万元 的，须报采购委员会审批；低于该额度的由部门负责人审批。"),
        ("h2", "三、供应商管理"),
        ("p", "供应商准入评估每 2 年 复核一次，连续两次评估不合格的应移出入库。"),
        ("h2", "四、时限要求"),
        ("table", [
            ["环节", "时限", "责任部门"],
            ["需求提报", "3 个工作日", "业务部门"],
            ["采购评审", "5 个工作日", "采购中心"],
        ]),
    ]
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    path = os.path.join(HERE, "sample_doc.docx")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", _docx_xml(blocks))


if __name__ == "__main__":
    build_text()
    build_scanned()
    build_docx()
    for name in ("sample_text.pdf", "sample_scanned.pdf", "sample_doc.docx"):
        path = os.path.join(HERE, name)
        print(f"{name}: {os.path.getsize(path)} bytes")
