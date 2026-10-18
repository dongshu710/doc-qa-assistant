"""统一文档入库：按扩展名分派解析器，产出知识库里的 Markdown。

PDF → `pdf_ingest`（pypdf / 内置解析）
DOCX → `docx_text`（纯标准库 zip + XML）

对外只有 `ingest_bytes()` 一个入口，服务端与命令行共用，避免「上传」和「批量导入」
两套逻辑各写一遍、行为漂移。
"""
from __future__ import annotations

from pathlib import Path

from . import docx_text, pdf_ingest

SUPPORTED_EXT = (".pdf", ".docx")
DEFAULT_MIN_CHARS = pdf_ingest.DEFAULT_MIN_CHARS


def ingest_bytes(data: bytes, filename: str, out_dir: str | Path,
                 engine: str = "auto", min_chars: int = DEFAULT_MIN_CHARS) -> dict:
    """把一份 PDF / DOCX 的字节流变成知识库 Markdown。

    返回统一结构：`{ok, md, chars, engine, pages?, paragraphs?, note?, error?}`
    """
    ext = Path(filename).suffix.lower()
    out = Path(out_dir)

    if ext == ".pdf":
        res = pdf_ingest.pdf_bytes_to_markdown(
            data, filename, out, engine=engine, min_chars=min_chars)
        res.setdefault("format", "pdf")
        return res

    if ext == ".docx":
        title = Path(filename).stem
        try:
            md_text, meta = docx_text.extract_docx(data, title=title)
        except docx_text.DocxError as exc:
            return {"ok": False, "error": str(exc), "format": "docx"}

        chars = int(meta.get("chars") or 0)
        if chars < min_chars:
            return {"ok": False, "format": "docx", "chars": chars,
                    "error": f"提取到 {chars} 字，低于阈值 {min_chars} 字。"
                             "文档可能全是图片或文本框，需要先转成可复制文字。"}

        out.mkdir(parents=True, exist_ok=True)
        target = pdf_ingest.unique_path(out, f"docx_{pdf_ingest.safe_stem(title)}.md")
        target.write_text(md_text, encoding="utf-8")
        return {
            "ok": True,
            "md": target.name,
            "chars": chars,
            "engine": meta["engine"],
            "paragraphs": meta.get("paragraphs"),
            "tables": meta.get("tables"),
            "headings": meta.get("headings"),
            "note": None,
            "format": "docx",
        }

    return {"ok": False, "error": f"不支持的文件类型 {ext or '（无扩展名）'}，只接受 PDF / DOCX",
            "format": ext.lstrip(".")}
