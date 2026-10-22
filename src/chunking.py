"""标题/条款感知切分。

为什么不按固定字符数硬切：固定窗口会把表格、条款从中间截断，是 RAG 塌方的头号原因
（典型 badcase：「文档切太碎，把表格拆断」）。这里按 Markdown 标题与「第X条」切，
保证每个 chunk 语义完整、可回溯到出处。
"""
import os
import re
from dataclasses import dataclass
from typing import Callable


@dataclass
class Chunk:
    doc_id: str
    title: str
    section: str
    text: str
    chunk_index: int


def _split_section(body: str, max_chars: int = 320) -> list[str]:
    """把一节正文按「第X条」切成语义完整的块；超长条款再按句号兜底。"""
    pieces = [p.strip() for p in re.split(r"(?=第[一二三四五六七八九十百零\d]+条)", body) if p.strip()]
    if not pieces:
        pieces = [body.strip()]
    out: list[str] = []
    for p in pieces:
        if len(p) <= max_chars:
            out.append(p)
        else:
            buf = ""
            for s in re.split(r"(?<=[。；;])", p):
                if not s:
                    continue
                if len(buf) + len(s) > max_chars and buf:
                    out.append(buf)
                    buf = s
                else:
                    buf += s
            if buf:
                out.append(buf)
    return [x for x in out if x]


def parse_document(raw: str, fname: str) -> list[Chunk]:
    """解析单份文档。拆出来是为了让增量重建只重读变更过的文件。"""
    chunks: list[Chunk] = []
    doc_id = fname.rsplit(".", 1)[0]
    title = doc_id
    section = "概述"
    buf: list[str] = []
    idx = 0

    def flush(doc: str, doc_title: str, section_name: str) -> None:
        nonlocal buf, idx
        body = "\n".join(buf).strip()
        if body:
            for piece in _split_section(body):
                chunks.append(Chunk(doc, doc_title, section_name, piece, idx))
                idx += 1
        buf = []

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            flush(doc_id, title, section)
            if stripped.startswith("# "):
                title = stripped[2:].strip() or title
                section = "概述"
            else:
                section = stripped.lstrip("#").strip() or section
            continue
        buf.append(line)
    flush(doc_id, title, section)
    return chunks


def load_corpus(knowledge_dir: str, cache: dict | None = None,
                on_parse: Callable[[str], None] | None = None) -> list[Chunk]:
    """加载整库。

    `cache` 用于增量重建：fname -> (mtime_ns, size, chunks)。签名不变的文件
    直接复用上次解析结果，只重读变更/新增的文件；被删除的文档从缓存里清掉。
    解析结果只依赖文件内容，复用对象不会让新旧索引互相污染（Chunk 只读）。
    """
    chunks: list[Chunk] = []
    if not os.path.isdir(knowledge_dir):
        raise FileNotFoundError(f"知识库目录不存在: {knowledge_dir}")

    seen = set()
    for fname in sorted(os.listdir(knowledge_dir)):
        if not fname.lower().endswith((".md", ".txt")):
            continue
        path = os.path.join(knowledge_dir, fname)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        signature = (stat.st_mtime_ns, stat.st_size)
        seen.add(fname)
        cached = cache.get(fname) if cache is not None else None
        if cached and cached[0] == signature:
            chunks.extend(cached[2])
            continue
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        parsed = parse_document(raw, fname)
        if cache is not None:
            cache[fname] = (signature, stat.st_size, parsed)
        if on_parse:
            on_parse(fname)
        chunks.extend(parsed)

    if cache is not None:
        for stale in [name for name in cache if name not in seen]:
            cache.pop(stale, None)

    return chunks
