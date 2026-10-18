"""内置 PDF 解析器的单元测试（纯标准库，不依赖 pypdf）。

只测「自己写的这部分」：对象流、字体解码、失败路径。
与 pypdf 的一致性对比放在人工验证里（见 README 4.3）。
"""
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.pdf_text import PDFError, extract_text  # noqa: E402


def _objstm_pdf() -> bytes:
    """页面字典与字体放在压缩对象流里的最小 PDF。"""
    page = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 6 0 R >>")
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    bodies, nums = [page, font], [3, 4]
    offsets, cur = [], 0
    for b in bodies:
        offsets.append(cur)
        cur += len(b) + 1
    header = b" ".join(b"%d %d" % (n, o) for n, o in zip(nums, offsets)) + b" "
    comp = zlib.compress(header + b"\n".join(bodies))
    content = b"BT /F1 24 Tf 40 120 Td (HELLO OBJSTM) Tj ET"
    objstm_head = (b"5 0 obj << /Type /ObjStm /N 2 /First %d /Filter /FlateDecode "
                   b"/Length %d >> stream\n" % (len(header), len(comp)))
    content_obj = (b"6 0 obj << /Length %d >> stream\n" % len(content))
    return b"".join([
        b"%PDF-1.5\n",
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        objstm_head, comp, b"\nendstream endobj\n",
        content_obj, content, b"\nendstream endobj\n",
        b"trailer << /Root 1 0 R >>\n%%EOF",
    ])


def test_objstm() -> None:
    text, meta = extract_text(_objstm_pdf())
    assert meta["pages"] == 1, meta
    assert text.strip() == "HELLO OBJSTM", repr(text)
    print("[1] 对象流 + 简单字体：", repr(text))


def test_reject() -> None:
    for label, data, needle in [
        ("非 PDF", b"hello world", "%PDF"),
        ("空文件", b"", "%PDF"),
        ("加密", b"%PDF-1.5\n1 0 obj << >> endobj\ntrailer << /Encrypt 9 0 R >>", "加密"),
    ]:
        try:
            extract_text(data)
        except PDFError as exc:
            assert needle in str(exc), (label, str(exc))
            print(f"[2] {label} 被拒：{exc}")
        else:
            raise AssertionError(f"{label} 应该报错")
    print("PDF 解析器单元测试通过")


if __name__ == "__main__":
    test_objstm()
    test_reject()
