"""纯标准库 PPTX 取文本（零第三方依赖）。

PPTX 也是 ZIP：每页幻灯片在 `ppt/slides/slideN.xml`，文字在 `<a:t>` 里。
为什么要做它：路演材料、产品介绍几乎都是 PPT，用户第一次上传就撞上「不支持」，
而这类文件里恰恰有大量条款之外的口径描述（费率怎么算、期限怎么分档）。

能力边界（写清楚，不假装支持）：
- 支持：每页的文字框、标题、表格里的文字；按页生成 `## 第 N 页` 章节。
- 不支持：图片/图表里的文字（无 OCR）、演讲者备注（`notesSlides` 里多是口播稿，
  混进正文会污染检索）、SmartArt 与嵌入对象、动画与版式含义。
- 页码来自 `slideN.xml` 的 N，不是文件里的显示顺序。两者在手工改名后会不一致，
  但 N 至少是稳定的，且与 PowerPoint 左侧序号通常一致。
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

from . import zipguard

# 与 `pdf_ingest.PAGE_MARK` / `chunking` 同一个格式约定，改要三处一起改。
PAGE_MARK = "<!--page:{n}-->"

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
MAX_SLIDES = 300          # 单份最多取多少页：再多已经不适合塞进上下文
MAX_CHARS = 400_000       # 全部文字上限，防止异常文件把内存吃满


class PptxError(RuntimeError):
    pass


def _clean(text: str) -> str:
    return re.sub(r"[ \t\u3000\xa0]+", " ", text).strip()


def _slide_text(xml: bytes) -> list[str]:
    """取一页里的段落文本。

    按 `<a:p>` 分段而不是把所有 `<a:t>` 拼起来：一个文本框里的多段在 PPT 里
    是并列要点，拼成一行会让「第一条…第二条…」变成一句话，切分器找不到边界。
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    lines: list[str] = []
    for paragraph in root.iter(f"{_A}p"):
        parts = [(node.text or "") for node in paragraph.iter(f"{_A}t")]
        text = _clean("".join(parts))
        if text:
            lines.append(text)
    return lines


def extract_pptx(data: bytes, title: str = "") -> tuple[str, dict]:
    """返回 (Markdown, 统计信息)。"""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PptxError("不是有效的 PPTX（ZIP 结构损坏）") from exc

    with archive:
        try:
            zipguard.guard(archive)
        except zipguard.ZipLimitError as exc:
            raise PptxError(str(exc)) from exc

        slides: list[tuple[int, list[str]]] = []
        for name in archive.namelist():
            match = _SLIDE_RE.match(name)
            if not match:
                continue
            slides.append((int(match.group(1)), _slide_text(archive.read(name))))
        if not slides:
            raise PptxError("PPTX 里没有幻灯片（ppt/slides 为空，可能是空文件或纯图片）")
        slides.sort(key=lambda item: item[0])

    out: list[str] = [f"# {_clean(title) or '演示文稿'}", ""]
    used = 0
    kept = 0
    empty = 0
    for number, lines in slides[:MAX_SLIDES]:
        if not lines:
            # 纯图页保留一句占位：整页跳过会让后面的页码前移，引用就指错页了
            empty += 1
            out.extend([f"## 第 {number} 页", "", PAGE_MARK.format(n=number),
                        "（本页只有图片或图表，无可提取文字）", ""])
            continue
        block = "\n".join(lines)
        if used + len(block) > MAX_CHARS:
            break
        used += len(block)
        kept += 1
        # 标题给人看，页标记给切分器看（换算成 Chunk.page，再从正文剥掉）。
        # 只写标题的话引用里 `page` 永远是 null——PPT 明明有页，却显示不出来。
        out.extend([f"## 第 {number} 页", "", PAGE_MARK.format(n=number)])
        out.extend(lines)
        out.append("")
    md = "\n".join(out).strip() + "\n"
    return md, {
        "engine": "builtin-pptx",
        "slides": len(slides),
        "slides_text": kept,
        "slides_empty": empty,
        "chars": used,
        "truncated": len(slides) > MAX_SLIDES or used >= MAX_CHARS,
    }
