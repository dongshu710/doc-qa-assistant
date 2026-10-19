"""检索层：向量召回 + 重排（默认），并保留 BM25 / Hybrid 作为对照。

当前默认链路：
1. **向量召回**：字符 2/3-gram + 词元的 hashing TF-IDF 向量，取 topN 候选；
2. **重排**：对候选综合「向量相似度 + 原问题词覆盖 + 长片段命中 + BM25 分 + 标题/章节命中」，
   输出 0~1 的归一化分数，供 pipeline 的置信度闸门使用；
3. BM25 与 Hybrid 仍保留，可通过 `RETRIEVAL=bm25|hybrid|vector` 切换。

诚实说明（不要被「向量」二字误导）：
这里的向量是 **hashing TF-IDF 向量**（字符 2/3-gram 哈希到固定维度），
是**词法相似度**，不是语义 embedding。同义改写（「起购」vs「起点」）仍然靠
查询扩展（`src/query.py`，可选 LLM 改写）来补。`VectorIndex` 的接口已隔离，
将来可直接替换为真 embedding 向量库，不影响召回/重排调用方。
"""
import math
import re
import zlib
from collections import Counter

_ALNUM_RE = re.compile(r"[a-z]+|\d+(?:\.\d+)?")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """中文二元组 + 英文/数字原词。"""
    text = text.lower()
    tokens: list[str] = _ALNUM_RE.findall(text)
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


class BM25:
    def __init__(self, chunks, k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.docs: list[Counter] = []
        self.doc_len: list[int] = []
        self.df: Counter = Counter()

        for c in chunks:
            toks = tokenize(c.section + " " + c.text)
            self.docs.append(Counter(toks))
            self.doc_len.append(len(toks))
            for t in set(toks):
                self.df[t] += 1

        self.N = len(chunks)
        self.avgdl = (sum(self.doc_len) / self.N) if self.N else 0.0
        self.idf = {
            t: math.log(1 + (self.N - df + 0.5) / (df + 0.5))
            for t, df in self.df.items()
        }

    def search(self, query: str, top_k: int = 4, focus_query: str | None = None):
        """focus_query 仅为接口兼容（BM25 无扩展词，召回即重排）。"""
        q = tokenize(query)
        if not q or not self.N:
            return []
        scores: list[tuple[float, int]] = []
        for i, d in enumerate(self.docs):
            s = 0.0
            dl = self.doc_len[i]
            denom_base = self.k1 * (1 - self.b + self.b * dl / self.avgdl) if self.avgdl else self.k1
            for t in q:
                tf = d.get(t, 0)
                if not tf:
                    continue
                idf = self.idf.get(t, 0.0)
                s += idf * (tf * (self.k1 + 1)) / (tf + denom_base)
            if s > 0:
                scores.append((s, i))
        scores.sort(key=lambda x: x[0], reverse=True)
        return [(self.chunks[i], round(s, 4)) for s, i in scores[:top_k]]


class VectorIndex:
    """字符 2/3-gram + 词元的 hashing TF-IDF 向量（确定性哈希，跨进程稳定）。"""

    def __init__(self, chunks, dim: int = 8192):
        self.chunks = chunks
        self.dim = dim
        feats = [self._features(c.section + " " + c.text) for c in chunks]
        df: Counter = Counter()
        for f in feats:
            df.update(set(f))
        n = len(chunks)
        self.idf = {t: math.log((n + 1) / (d + 1)) + 1 for t, d in df.items()}
        self.vectors = [self._weigh(f) for f in feats]

    @staticmethod
    def _features(text: str) -> Counter:
        t = (text or "").lower()
        feats: Counter = Counter()
        for tok in _ALNUM_RE.findall(t):
            feats[tok] += 1
        for run in _CJK_RE.findall(t):
            for n in (2, 3):
                for i in range(len(run) - n + 1):
                    feats[run[i:i + n]] += 1
        return feats

    def _weigh(self, feats: Counter) -> dict[int, float]:
        vec: dict[int, float] = {}
        for tok, cnt in feats.items():
            idf = self.idf.get(tok)
            if idf is None:
                continue
            w = (1 + math.log(cnt)) * idf
            h = zlib.crc32(tok.encode("utf-8")) % self.dim
            vec[h] = vec.get(h, 0.0) + w
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {k: v / norm for k, v in vec.items()}

    def search(self, query: str, top_k: int = 4):
        qv = self._weigh(self._features(query))
        if not qv or not self.chunks:
            return []
        scored: list[tuple[float, int]] = []
        for i, dv in enumerate(self.vectors):
            # 稀疏点积：遍历较短的一侧
            small, big = (qv, dv) if len(qv) <= len(dv) else (dv, qv)
            s = sum(w * big.get(k, 0.0) for k, w in small.items())
            if s > 0:
                scored.append((s, i))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(self.chunks[i], round(s, 4)) for s, i in scored[:top_k]]


def _coverage(query_tokens: set[str], chunk_text: str) -> float:
    """查询词（去重）在片段中出现的比例——重排的核心信号。"""
    if not query_tokens:
        return 0.0
    toks = set(tokenize(chunk_text))
    return len(query_tokens & toks) / len(query_tokens)


def _long_match(query: str, chunk_text: str) -> float:
    """长片段命中：查询的 4-gram 是否出现在片段里，避免只看散词。"""
    q = re.sub(r"\s+", "", query.lower())
    t = re.sub(r"\s+", "", chunk_text.lower())
    if len(q) < 4:
        return 0.0
    grams = {q[i:i + 4] for i in range(len(q) - 3)}
    return 1.0 if any(g in t for g in grams) else 0.0


class HybridRetriever:
    """BM25 + 哈希向量，RRF 融合后再做轻量重排。

    返回分数已归一化到 0~1，语义为「相对置信度」，与 BM25 原始分不可直接比较；
    pipeline 的 min_score 阈值按检索模式分别设定（见 config.py）。
    """

    def __init__(self, chunks, dim: int = 8192, rrf_k: int = 60):
        self.chunks = chunks
        self.bm25 = BM25(chunks)
        self.vector = VectorIndex(chunks, dim=dim)
        self.rrf_k = rrf_k
        self._index = {id(c): i for i, c in enumerate(chunks)}

    def search(self, query: str, top_k: int = 4, focus_query: str | None = None):
        """query 用于召回（可含扩展词），focus_query 用于重排（应为用户原问题）。

        为什么分开：扩展词能扩大召回面，但按扩展词算覆盖率会把「原问题最相关」的块压下去
        （实测 H10 修好后，其他题的 R@1 从 72.7% 掉到 63.6%）。召回求广，重排求准。
        """
        cand = max(20, top_k * 5)
        lex = self.bm25.search(query, cand)
        vec = self.vector.search(query, cand)
        if not lex and not vec:
            return []

        rrf: dict[int, float] = {}
        for rank, (chunk, _s) in enumerate(lex):
            idx = self._index[id(chunk)]
            rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (self.rrf_k + rank + 1)
        for rank, (chunk, _s) in enumerate(vec):
            idx = self._index[id(chunk)]
            rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (self.rrf_k + rank + 1)

        focus = focus_query or query
        q_tokens = set(tokenize(focus))
        max_rrf = max(rrf.values()) or 1.0
        reranked: list[tuple[float, int]] = []
        for idx, rrf_score in rrf.items():
            chunk = self.chunks[idx]
            text = chunk.section + " " + chunk.text
            score = (
                0.55 * (rrf_score / max_rrf)
                + 0.30 * _coverage(q_tokens, text)
                + 0.15 * _long_match(focus, text)
            )
            reranked.append((round(score, 4), idx))
        reranked.sort(key=lambda x: x[0], reverse=True)
        return [(self.chunks[i], s) for s, i in reranked[:top_k]]


class VectorRerankRetriever:
    """向量召回 + 多信号重排（项目默认检索器）。

    召回只走向量索引，保证「问法与原文不完全一致」时也能进入候选；
    重排再引入原问题词覆盖、长片段命中、BM25 与标题命中，避免向量分
    把「字面像但答非所问」的块排到前面。

    分数归一化到 0~1，语义是「相对置信度」，不是概率。
    """

    def __init__(self, chunks, dim: int = 8192, recall_k: int = 48):
        self.chunks = chunks
        self.vector = VectorIndex(chunks, dim=dim)
        self.bm25 = BM25(chunks)
        self.recall_k = max(24, recall_k)

    def search(self, query: str, top_k: int = 4, focus_query: str | None = None):
        """query 用于向量召回（可含扩展词），focus_query 用于重排（原问题）。"""
        candidates = self.vector.search(query, max(self.recall_k, top_k * 8))
        if not candidates:
            return []

        focus = focus_query or query
        q_tokens = set(tokenize(focus))
        lex = {id(c): s for c, s in self.bm25.search(query, len(self.chunks))}
        max_vec = candidates[0][1] or 1.0
        max_lex = max(lex.values()) if lex else 1.0

        reranked: list[tuple[float, int]] = []
        index = {id(c): i for i, c in enumerate(self.chunks)}
        for chunk, vec_score in candidates:
            text = chunk.section + " " + chunk.text
            lex_score = lex.get(id(chunk), 0.0)
            score = (
                0.45 * (vec_score / max_vec)
                + 0.25 * _coverage(q_tokens, text)
                + 0.15 * (lex_score / max_lex if max_lex else 0.0)
                + 0.10 * _long_match(focus, text)
                + 0.05 * _coverage(q_tokens, chunk.title + " " + chunk.section)
            )
            reranked.append((round(score, 4), index[id(chunk)]))

        reranked.sort(key=lambda x: x[0], reverse=True)
        return [(self.chunks[i], s) for s, i in reranked[:top_k]]


def build_retriever(chunks, mode: str = "vector", rrf_k: int = 60):
    """检索器工厂（唯一入口，调用方不感知具体实现）。

    mode:
      - `vector`（默认）：向量召回 + 重排
      - `bm25`：纯词法，用于对照与降级
      - `hybrid`：BM25 + 向量 RRF 融合 + 重排，用于历史对照
    """
    if mode == "bm25":
        return BM25(chunks)
    if mode == "hybrid":
        return HybridRetriever(chunks, rrf_k=rrf_k)
    return VectorRerankRetriever(chunks)
