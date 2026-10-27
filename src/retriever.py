"""检索层：真 embedding 召回 + 重排（`RETRIEVAL=embedding`），保留词法基线对照。

四种模式，共用同一套 `search()` 接口：
- `embedding`：真 embedding（OpenAI 兼容 /embeddings，bge 同协议）+ 向量索引召回，
  再按「余弦 + 原问题词覆盖 + BM25 + 长片段 + 标题」重排；
- `vector`：字符 2/3-gram hashing 向量召回 + 重排（零依赖基线，未配置模型时的兜底）；
- `hybrid`：BM25 + hashing 向量 RRF 融合 + 重排（历史对照）；
- `bm25`：纯词法（降级与对照）。

为什么重排不直接信余弦：embedding 的分数量纲随模型变化，且「语义相近但没答到点上」
的块很常见。把余弦归一为相对信号，再叠加词面覆盖与 BM25，能让阈值语义稳定，
也保留「问法与原文不一致」时的召回收益。

embedding 调用失败（超时/限流/维度错）不会让问答挂掉：当次请求回退 BM25 重排，
`last_error` 暴露给 pipeline 标记 `degraded`，健康检查里也能看到。
"""
import math
import re
import zlib
from collections import Counter

from .embeddings import EmbeddingError, EmbeddingUnavailable, make_provider
from .vector_store import EmbeddingIndex

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

    def describe(self) -> dict:
        return {"mode": "bm25", "backend": "bm25", "chunks": len(self.chunks)}


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

    def describe(self) -> dict:
        return {"mode": "hybrid", "backend": "bm25+hash-ngram", "chunks": len(self.chunks)}


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

    def describe(self) -> dict:
        return {"mode": "vector", "backend": "hash-ngram", "chunks": len(self.chunks)}


class EmbeddingRetriever:
    """真 embedding 召回 + 多信号重排。

    索引在构造时 `ensure()`：manifest 与语料/模型匹配就直接加载，
    否则重新 embedding 并原子写盘。查询向量带 128 条 LRU 缓存，
    同一问题在多轮追问/评测重跑时不重复计费。
    """

    def __init__(self, chunks, provider, index_dir: str, store_kind: str = "auto",
                 recall_k: int = 48, nlist: int = 64, nprobe: int = 8,
                 build_budget_s: float | None = None):
        self.chunks = chunks
        self.provider = provider
        self.bm25 = BM25(chunks)
        self.recall_k = max(24, recall_k)
        self.index = EmbeddingIndex(chunks, provider, index_dir, store_kind, nlist, nprobe,
                                    build_budget_s=build_budget_s)
        try:
            self.index_status = self.index.ensure()
        except EmbeddingError:
            raise
        except Exception as exc:  # noqa: BLE001 —— 索引后端异常统一转成可降级的错误
            raise EmbeddingError(
                f"索引构建失败: {type(exc).__name__}: {exc}") from exc
        self.last_error: str | None = None
        self._query_cache: dict[str, list[float]] = {}
        self._cache_order: list[str] = []

    def _embed_query(self, query: str) -> tuple[list[float], dict]:
        """返回 (向量, 用量)。用量跟着返回值走，不落实例字段——并发会串账。"""
        hit = self._query_cache.get(query)
        if hit is not None:
            return hit, {}
        result = self.provider.embed([query])
        vec = result.vectors[0]
        self._query_cache[query] = vec
        self._cache_order.append(query)
        if len(self._cache_order) > 128:
            self._query_cache.pop(self._cache_order.pop(0), None)
        return vec, result.usage

    def search_ex(self, query: str, top_k: int = 4, focus_query: str | None = None):
        """返回 (hits, meta)。meta = {degraded, error, tokens}。

        为什么不用 `last_error` / `last_usage` 传这两个值：它们是实例字段，
        `ThreadingHTTPServer` 下两个请求交错时，A 的 embedding 失败会被记到 B 的
        `degraded` 上，token 也会算到别人账上。按返回值传递，天然线程安全。
        `last_error` 仍保留，只用于健康检查展示「最近一次错误」。
        """
        focus = focus_query or query
        try:
            qv, usage = self._embed_query(query)
            candidates = self.index.search(qv, max(self.recall_k, top_k * 8))
            self.last_error = None
        except EmbeddingError as exc:
            # 失败降级：当次用 BM25 召回，分数仍归一化，保证闸门语义一致
            hits = self._fallback(query, focus, top_k, str(exc))
            return hits, {"degraded": True, "error": str(exc)[:300], "tokens": 0}

        tokens = int((usage or {}).get("total_tokens") or 0)
        meta = {"degraded": False, "error": None, "tokens": tokens}
        if not candidates:
            return [], meta

        q_tokens = set(tokenize(focus))
        lex = {id(c): s for c, s in self.bm25.search(query, len(self.chunks))}
        max_lex = max(lex.values()) if lex else 1.0

        reranked: list[tuple[float, int]] = []
        for idx, cos in candidates:
            if not 0 <= idx < len(self.chunks):
                continue
            chunk = self.chunks[idx]
            text = chunk.section + " " + chunk.text
            score = (
                0.50 * max(0.0, cos)
                + 0.20 * _coverage(q_tokens, text)
                + 0.15 * (lex.get(id(chunk), 0.0) / max_lex if max_lex else 0.0)
                + 0.10 * _long_match(focus, text)
                + 0.05 * _coverage(q_tokens, chunk.title + " " + chunk.section)
            )
            reranked.append((round(score, 4), idx))

        reranked.sort(key=lambda x: x[0], reverse=True)
        return [(self.chunks[i], s) for s, i in reranked[:top_k]], meta

    def search(self, query: str, top_k: int = 4, focus_query: str | None = None):
        """兼容旧调用：只要命中块。需要降级原因与用量时用 `search_ex`。"""
        hits, _meta = self.search_ex(query, top_k, focus_query)
        return hits

    def _fallback(self, query: str, focus: str, top_k: int, error: str):
        self.last_error = error
        hits = self.bm25.search(query or focus, max(self.recall_k, top_k * 8))
        if not hits:
            return []
        q_tokens = set(tokenize(focus))
        max_lex = hits[0][1] or 1.0
        reranked = []
        for chunk, lex in hits:
            text = chunk.section + " " + chunk.text
            score = (
                0.55 * (lex / max_lex)
                + 0.25 * _coverage(q_tokens, text)
                + 0.10 * _long_match(focus, text)
                + 0.10 * _coverage(q_tokens, chunk.title + " " + chunk.section)
            )
            reranked.append((chunk, round(score, 4)))
        reranked.sort(key=lambda x: x[1], reverse=True)
        return reranked[:top_k]

    def describe(self) -> dict:
        return {
            "mode": "embedding",
            "backend": self.index_status.get("backend"),
            "model": self.provider.model,
            "dim": self.index_status.get("dim"),
            "index_status": self.index_status.get("status"),
            "index_dir": self.index_status.get("index_dir"),
            "chunks": len(self.chunks),
            "degraded": bool(self.last_error),
            "last_error": self.last_error,
        }


def build_retriever(chunks, mode: str = "vector", rrf_k: int = 60,
                    settings=None, index_dir: str | None = None):
    """检索器工厂（唯一入口，调用方不感知具体实现）。

    mode:
      - `embedding`：真 embedding + 向量索引召回 + 重排
      - `vector`（默认）：hashing n-gram 向量召回 + 重排，零依赖
      - `bm25`：纯词法，用于对照与降级
      - `hybrid`：BM25 + hashing 向量 RRF 融合 + 重排，用于历史对照
    """
    if mode == "bm25":
        return BM25(chunks)
    if mode == "hybrid":
        return HybridRetriever(chunks, rrf_k=rrf_k)
    if mode == "embedding":
        if settings is None:
            raise EmbeddingUnavailable("embedding 检索需要 Settings")
        provider = make_provider(settings)
        if provider is None:
            raise EmbeddingUnavailable(
                "未配置 EMBEDDING_PROVIDER；请设置 EMBEDDING_BASE_URL / EMBEDDING_MODEL"
            )
        return EmbeddingRetriever(
            chunks, provider,
            index_dir=index_dir or getattr(settings, "embedding_index_dir", "data/index"),
            store_kind=getattr(settings, "vector_store", "auto"),
            recall_k=getattr(settings, "embedding_recall_k", 48),
            nlist=getattr(settings, "vector_ivf_nlist", 64),
            nprobe=getattr(settings, "vector_ivf_nprobe", 8),
            build_budget_s=getattr(settings, "embedding_build_budget_s", 600.0),
        )
    return VectorRerankRetriever(chunks)
