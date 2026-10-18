"""标题/条款感知切分。

为什么不按固定字符数硬切：固定窗口会把表格、条款从中间截断，是 RAG 塌方的头号原因
（手册 2.5 的 badcase：「文档切太碎，把表格拆断」）。这里按 Markdown 标题与「第X条」切，
保证每个 chunk 语义完整、可回溯到出处。
"""
import os
import re
from dataclasses import dataclass


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


def load_corpus(knowledge_dir: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    if not os.path.isdir(knowledge_dir):
        raise FileNotFoundError(f"知识库目录不存在: {knowledge_dir}")

    for fname in sorted(os.listdir(knowledge_dir)):
        if not fname.lower().endswith((".md", ".txt")):
            continue
        path = os.path.join(knowledge_dir, fname)
        with open(path, encoding="utf-8") as f:
            raw = f.read()

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
