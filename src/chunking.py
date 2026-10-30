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


# 「自动」不是 0：0 只在当前语料恰好全短时才安全，换一份带长条款的合同就会丢跨块指代。
# None 表示按内容自适应，真实数字才是用户显式指定的行为。
AUTO = None


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, "") or default))
    except (TypeError, ValueError):
        return default


def _env_overlap(default=None) -> int | None:
    """读 `CHUNK_OVERLAP`：空 / auto / none → 自适应，数字 → 显式值，坏值 → 回到默认。

    坏值不能当成 0（等于悄悄关掉重叠），也不能崩——回落到 `default` 才是
    「配置写错了，但服务照常」的正确语义。
    """
    raw = (os.environ.get("CHUNK_OVERLAP") or "").strip()
    if not raw:
        return default
    if raw.lower() in ("auto", "none", "off-auto"):
        return AUTO
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _needs_overlap(pieces: list[str], max_chars: int) -> bool:
    """本节是否存在「会被句号兜底切开」的超长条款。

    自适应重叠的成本全在这里：只有确实会走兜底分支时才值得付。
    """
    return any(len(p) > max_chars for p in pieces)


def _split_section(body: str, max_chars: int = 320, overlap: int | None = AUTO) -> list[str]:
    """把一节正文按「第X条」切成语义完整的块；超长条款再按句号兜底。

    `overlap` 只作用于「超长条款被句号切开」这条路径：按「第X条」切出来的
    每一块本身就是完整条款，再加重叠只会让相邻块互相污染分数。
    被句号切开的地方则常见「该产品」「上述期限」这类跨块指代，带上上一块
    的尾巴能救回来。

    `overlap=None`（默认）＝按本节内容判断：有超长条款才带上上一块尾巴，
    否则退化成 0。这样换语料不会因为「默认值恰好为 0」而静默丢上下文。
    """
    pieces = [p.strip() for p in re.split(r"(?=第[一二三四五六七八九十百零\d]+条)", body) if p.strip()]
    if not pieces:
        pieces = [body.strip()]
    if overlap is AUTO:
        # 自动档取 1/5，比显式上限（1/4）保守：兜底切分本就少见，不必叠太厚
        span = max_chars // 5 if _needs_overlap(pieces, max_chars) else 0
    else:
        span = min(max(0, overlap), max_chars // 4)   # 重叠不能吃掉整块
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
                    buf = (buf[-span:] if span else "") + s
                else:
                    buf += s
            if buf:
                out.append(buf)
    return [x for x in out if x]


def parse_document(raw: str, fname: str, max_chars: int = 320,
                   overlap: int | None = AUTO) -> list[Chunk]:
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
            for piece in _split_section(body, max_chars, overlap):
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
                on_parse: Callable[[str], None] | None = None,
                max_chars: int | None = None, overlap: int | None = None) -> list[Chunk]:
    """加载整库。

    `cache` 用于增量重建：fname -> (签名, size, chunks)。签名不变的文件
    直接复用上次解析结果，只重读变更/新增的文件；被删除的文档从缓存里清掉。
    解析结果只依赖文件内容，复用对象不会让新旧索引互相污染（Chunk 只读）。

    签名里带上切分参数：改了 `CHUNK_OVERLAP` 但文件没动时，如果只看 mtime/size，
    旧分块会被静默复用——「改了配置没生效」比报错更难查。
    `overlap=None` 表示交给环境变量（默认 auto），显式传数字则覆盖。
    """
    max_chars = _env_int("CHUNK_MAX_CHARS", 320) if max_chars is None else max_chars
    overlap = _env_overlap(AUTO) if overlap is None else overlap
    # auto 的结果取决于文档内容，而内容变了签名也会变；这里用固定标记让
    # 「auto 与显式 0」在缓存里不互相冒充。
    overlap_tag = "auto" if overlap is AUTO else overlap
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
        signature = (stat.st_mtime_ns, stat.st_size, max_chars, overlap_tag)
        seen.add(fname)
        cached = cache.get(fname) if cache is not None else None
        if cached and cached[0] == signature:
            chunks.extend(cached[2])
            continue
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        parsed = parse_document(raw, fname, max_chars, overlap)
        if cache is not None:
            cache[fname] = (signature, stat.st_size, parsed)
        if on_parse:
            on_parse(fname)
        chunks.extend(parsed)

    if cache is not None:
        for stale in [name for name in cache if name not in seen]:
            cache.pop(stale, None)

    return chunks
