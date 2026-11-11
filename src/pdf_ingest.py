"""PDF → Markdown 预处理：离线批量 + 上传即用，共用同一套逻辑。

两套解析引擎，同一接口：
- `pypdf`：若已安装（.venv 里装了）优先用它，兼容性最好；
- `builtin`：`src/pdf_text.py` 的纯标准库实现，保证运行时零第三方依赖
  （实测与 pypdf 在三份制度 PDF 上逐字符一致）。

用法：
  python -m src.pdf_ingest --raw data/raw --out data/knowledge     # 批量
  python -m src.pdf_ingest --file 某制度.pdf --out data/knowledge  # 单份
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from . import pdf_text

_HEADING_PATTERNS = [
    r"^第[一二三四五六七八九十百零]+[章节]",
    r"^[一二三四五六七八九十]+、",
    r"^（[一二三四五六七八九十]+）",
]

DEFAULT_MIN_CHARS = 50


def _engine_order(engine: str) -> list[str]:
    if engine in ("pypdf", "builtin"):
        return [engine]
    order = []
    try:
        import pypdf  # noqa: F401
        order.append("pypdf")
    except ImportError:
        pass
    order.append("builtin")
    return order


# 页标记：写进 Markdown 的 HTML 注释，切分时用它给 chunk 定页码，随后被剥掉。
#
# 为什么写进文件而不是另存一份页码映射：切分发生在「以后某次重建索引」时，
# 那时手里只有 Markdown。映射表要跟着版本目录一起搬、还要防它和文件不同步，
# 而一个注释行是自描述的——文件在，页码就在。
PAGE_MARK = "<!--page:{n}-->"
PAGE_MARK_RE = re.compile(r"<!--page:(\d+)-->")


def extract_pages(source: bytes | str | Path,
                  engine: str = "auto") -> tuple[list[tuple[int, str]], dict]:
    """按页抽文本：`[(页码, 文本), ...]`。空页保留为空串（页码不能前移）。"""
    if isinstance(source, (str, Path)):
        data = Path(source).read_bytes()
    else:
        data = source

    errors: list[str] = []
    for name in _engine_order(engine):
        try:
            if name == "pypdf":
                import io

                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(data))
                pages = [(index, clean(page.extract_text() or ""))
                         for index, page in enumerate(reader.pages, 1)]
                joined = "\n\n".join(text for _n, text in pages if text)
                return pages, {"engine": "pypdf", "pages": len(pages),
                               "chars": len(joined)}
            pages, meta = pdf_text.extract_pages(data)
            pages = [(number, clean(text)) for number, text in pages]
            return pages, meta
        except Exception as exc:  # noqa: BLE001 —— 换引擎再试，最后统一报错
            errors.append(f"{name}: {exc}")

    raise pdf_text.PDFError("；".join(errors) or "PDF 解析失败")


def with_page_marks(pages: list[tuple[int, str]]) -> str:
    """把分页文本拼成带页标记的全文。空页只留标记，不产出空行堆。"""
    parts: list[str] = []
    for number, text in pages:
        if not text:
            continue
        parts.append(PAGE_MARK.format(n=number))
        parts.append(text)
    return "\n\n".join(parts)


def strip_page_marks(text: str) -> str:
    """去掉页标记并收拾多余空行；给「看原文」这类展示用。"""
    out = PAGE_MARK_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def extract_text(source: bytes | str | Path, engine: str = "auto") -> tuple[str, dict]:
    """抽取 PDF 文本。source 可以是字节或路径。返回 (文本, 统计信息)。"""
    if isinstance(source, (str, Path)):
        data = Path(source).read_bytes()
    else:
        data = source

    errors: list[str] = []
    for name in _engine_order(engine):
        try:
            if name == "pypdf":
                import io

                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(data))
                pages = [(page.extract_text() or "") for page in reader.pages]
                text = clean("\n".join(pages))
                return text, {"engine": "pypdf", "pages": len(pages), "chars": len(text)}
            text, meta = pdf_text.extract_text(data)
            return clean(text), meta
        except Exception as exc:  # noqa: BLE001 —— 换引擎再试，最后统一报错
            errors.append(f"{name}: {exc}")

    raise pdf_text.PDFError("；".join(errors) or "PDF 解析失败")


def clean(text: str) -> str:
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def to_markdown(title: str, text: str) -> str:
    out = [f"# {title}", ""]
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if len(line) <= 40 and any(re.match(p, line) for p in _HEADING_PATTERNS):
            out.extend(["", f"## {line}", ""])
        else:
            out.append(line)
    return "\n".join(out).strip() + "\n"


def assess(text: str, pages: int, min_chars: int = DEFAULT_MIN_CHARS) -> str | None:
    """质量闸门：返回告警文案，None 表示可用。

    扫描件最典型的特征不是「0 字」而是「每页只有几十个杂字」（页眉页脚/水印），
    所以既看总字数，也看每页平均字数。
    """
    if len(text) < min_chars:
        return (f"提取到 {len(text)} 字，低于阈值 {min_chars} 字。"
                "这几乎一定是扫描件：整页是图片，没有可复制的文本层。"
                "请先用 OCR 转出文字（手机扫描类 App、Acrobat 的「识别文本」，"
                "或任意 OCR 工具），另存为 .docx / .txt 后重新上传；"
                "直接上传扫描 PDF 无法入库。")
    if pages and len(text) / pages < 20:
        return (f"共 {pages} 页但只有 {len(text)} 字（每页约 {len(text) // pages} 字）。"
                "先在阅读器里试着选中文字：选不中就是扫描件，需要 OCR；"
                "选得中则可能是排版异常，建议换成文字版 PDF 或 .docx。")
    return None


def unique_path(directory: Path, name: str) -> Path:
    """同名不覆盖：`a.md` 已存在就用 `a_2.md`，避免上传悄悄顶掉旧文档。"""
    target = directory / name
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    for i in range(2, 100):
        candidate = directory / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"{name} 同名文件过多")


def quality_note(meta: dict) -> str | None:
    """软告警：能入库但结果可能不干净（不阻断，只提示）。"""
    ratio = float(meta.get("unmapped_ratio") or 0)
    if ratio > 0.15:
        return (f"字体缺少 Unicode 映射（约 {round(ratio * 100)}% 的字符未能解码），"
                "文本可能夹杂乱码；建议换一份带文本层的导出文件")
    return None


def pdf_bytes_to_markdown(data: bytes, filename: str, out_dir: str | Path,
                          prefix: str = "pdf_", engine: str = "auto",
                          min_chars: int = DEFAULT_MIN_CHARS) -> dict:
    """把一个 PDF 字节流变成知识库里的 Markdown。返回统计信息（含告警）。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 一次解析同时拿到「全文」与「分页」：分两次解析等于把 PDF 解压两遍，
    # 大文件上是秒级开销，而两份结果还可能因为引擎兜底不同而不一致。
    page_list, meta = extract_pages(data, engine=engine)
    text = "\n\n".join(page_text for _n, page_text in page_list if page_text)
    pages = int(meta.get("pages") or 0)
    warn = assess(text, pages, min_chars=min_chars)
    if warn:
        # need_ocr 只标「文字量少到几乎可以断定是扫描件」的情况，
        # 前端据此显示具体的补救步骤，而不是一句笼统的失败
        need_ocr = len(text) < min_chars or bool(pages and len(text) / pages < 20)
        return {"ok": False, "error": warn, "need_ocr": need_ocr, **meta, "chars": len(text)}

    stem = Path(filename).stem or "document"
    target = unique_path(out, f"{prefix}{safe_stem(stem)}.md")
    target.write_text(to_markdown(stem, with_page_marks(page_list)), encoding="utf-8")
    return {
        "ok": True,
        "md": target.name,
        "pages": pages,
        "chars": len(text),
        "engine": meta.get("engine"),
        "warn": None,
        "note": quality_note(meta),
    }


def safe_stem(stem: str) -> str:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")
    return stem[:60] or "document"


def ingest_file(pdf_path: Path, out_dir: Path, prefix: str = "pdf_",
                min_chars: int = DEFAULT_MIN_CHARS, engine: str = "auto") -> dict:
    return pdf_bytes_to_markdown(pdf_path.read_bytes(), pdf_path.name, out_dir,
                                 prefix=prefix, engine=engine, min_chars=min_chars)


def main() -> None:
    ap = argparse.ArgumentParser(description="PDF → Markdown 预处理（pypdf 优先，内置解析兜底）")
    ap.add_argument("--raw", default="data/raw", help="批量模式：PDF 所在目录")
    ap.add_argument("--file", help="单份模式：指定一个 PDF")
    ap.add_argument("--out", default="data/knowledge")
    ap.add_argument("--prefix", default="pdf_")
    ap.add_argument("--min-chars", type=int, default=DEFAULT_MIN_CHARS)
    ap.add_argument("--engine", choices=["auto", "pypdf", "builtin"], default="auto")
    args = ap.parse_args()

    if args.file:
        pdfs = [Path(args.file)]
    else:
        pdfs = sorted(Path(args.raw).glob("*.pdf"))
        if not pdfs:
            print(f"未在 {args.raw} 找到 PDF")
            return

    for pdf_path in pdfs:
        try:
            res = ingest_file(pdf_path, Path(args.out), args.prefix,
                              args.min_chars, args.engine)
        except pdf_text.PDFError as exc:
            print(f"[fail] {pdf_path.name}: {exc}")
            continue
        if not res.get("ok"):
            print(f"[skip] {pdf_path.name}: {res.get('error')}")
            continue
        extra = f"｜注意：{res['note']}" if res.get("note") else ""
        print(f"[ok] {pdf_path.name} -> {res['md']}"
              f"（{res['pages']} 页 / {res['chars']} 字 / {res['engine']}）{extra}")


if __name__ == "__main__":
    main()
