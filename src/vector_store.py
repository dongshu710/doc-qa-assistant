"""向量存储与索引：纯 Python / NumPy / FAISS 三种后端，接口一致。

为什么默认选 FAISS 而不是 Chroma（本项目场景）：
- 语料是 10^2~10^5 量级的内部制度文档，**单进程、只读、按版本整体重建**，
  不需要 Chroma 的 collection 管理、元数据过滤和 HTTP 服务；
- FAISS `IndexFlatIP` 在这个量级是精确检索，召回率不打折，持久化就是两个文件；
- Chroma 会引入 sqlite/duckdb 等一串传递依赖，与「小依赖、可离线」的交付目标冲突。
  接口已隔离：将来要元数据过滤或多租户，再加 `ChromaStore` 即可，检索层不改。

索引文件（`data/index/<model>/`）：
- `manifest.json`：模型、维度、度量、语料指纹、后端、块数；
- `vectors.jsonl`：归一化后的向量（可移植，换后端不用重新 embedding）；
- `index.faiss`：FAISS 索引（可选，加载更快）。

一致性策略：manifest 里的 `fingerprint` 覆盖「模型 + 每块的 id/正文哈希」。
知识库或模型一变，指纹不匹配 → 自动重建；维度不一致 → 直接报错，不静默降级。
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import threading
from datetime import datetime, timezone

from .embeddings import EmbeddingCache, EmbeddingError

INDEX_FORMAT = 1


def l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if not norm:
        return [0.0] * len(vec)
    return [v / norm for v in vec]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _try_import_numpy():
    try:
        import numpy  # noqa: PLC0415 —— 可选依赖，延迟导入
        return numpy
    except ImportError:
        return None


def _try_import_faiss():
    try:
        import faiss  # noqa: PLC0415
        return faiss
    except ImportError:
        return None


class PureFlatStore:
    """纯 Python 精确内积；零依赖，作为所有环境的兜底。"""

    backend = "pure-flat"

    def __init__(self, dim: int):
        self.dim = dim
        self._vectors: list[list[float]] = []

    def add(self, vectors: list[list[float]]) -> None:
        for vec in vectors:
            if len(vec) != self.dim:
                raise ValueError(f"向量维度 {len(vec)} 与索引维度 {self.dim} 不一致")
            self._vectors.append(l2_normalize(vec))

    def search(self, query: list[float], k: int) -> list[tuple[int, float]]:
        q = l2_normalize(query)
        scored = []
        for i, vec in enumerate(self._vectors):
            score = sum(a * b for a, b in zip(q, vec))
            scored.append((i, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def __len__(self) -> int:
        return len(self._vectors)


class NumpyFlatStore:
    """NumPy 矩阵内积；比纯 Python 快一到两个数量级，依赖仅 numpy。"""

    backend = "numpy-flat"

    def __init__(self, dim: int):
        self.np = _try_import_numpy()
        if self.np is None:
            raise ImportError("numpy 未安装")
        self.dim = dim
        self._matrix = self.np.zeros((0, dim), dtype=self.np.float32)

    def add(self, vectors: list[list[float]]) -> None:
        arr = self.np.asarray(vectors, dtype=self.np.float32)
        if arr.ndim != 2 or arr.shape[1] != self.dim:
            raise ValueError(f"向量矩阵形状 {arr.shape} 与索引维度 {self.dim} 不一致")
        norms = self.np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        arr = arr / norms
        self._matrix = self.np.vstack([self._matrix, arr])

    def search(self, query: list[float], k: int) -> list[tuple[int, float]]:
        if not len(self._matrix):
            return []
        q = self.np.asarray(query, dtype=self.np.float32)
        norm = self.np.linalg.norm(q) or 1.0
        scores = self._matrix @ (q / norm)
        k = min(k, len(scores))
        idx = self.np.argpartition(-scores, k - 1)[:k]
        idx = idx[self.np.argsort(-scores[idx])]
        return [(int(i), float(scores[i])) for i in idx]

    def __len__(self) -> int:
        return int(self._matrix.shape[0])


class FaissStore:
    """FAISS 内积索引：flat 精确检索，ivf 走倒排（需训练）。

    小语料用 flat 就够了；ivf 只在 N 足够大（这里要求 ≥ nlist*30）时启用，
    否则训练样本不足会退化甚至报错，故自动回退 flat 并在 manifest 里记明。
    """

    def __init__(self, dim: int, kind: str = "flat", nlist: int = 64, nprobe: int = 8):
        self.faiss = _try_import_faiss()
        if self.faiss is None:
            raise ImportError("faiss 未安装")
        self.np = _try_import_numpy()
        if self.np is None:
            raise ImportError("faiss 后端需要 numpy")
        self.dim = dim
        self.kind = kind
        self.nlist = max(1, int(nlist))
        self.nprobe = max(1, int(nprobe))
        self._vectors: list[list[float]] = []
        self._index = None
        self.backend = "faiss-flat"

    def add(self, vectors: list[list[float]]) -> None:
        normed = [l2_normalize(v) for v in vectors]
        if any(len(v) != self.dim for v in normed):
            raise ValueError("向量维度与索引维度不一致")
        self._vectors.extend(normed)
        self._build()

    def _build(self) -> None:
        mat = self.np.asarray(self._vectors, dtype=self.np.float32)
        n = mat.shape[0]
        if self.kind == "ivf" and n >= self.nlist * 30:
            quantizer = self.faiss.IndexFlatIP(self.dim)
            index = self.faiss.IndexIVFFlat(
                quantizer, self.dim, self.nlist, self.faiss.METRIC_INNER_PRODUCT)
            index.train(mat)
            index.add(mat)
            index.nprobe = min(self.nprobe, self.nlist)
            self._index = index
            self.backend = f"faiss-ivf(nlist={self.nlist},nprobe={index.nprobe})"
        else:
            index = self.faiss.IndexFlatIP(self.dim)
            index.add(mat)
            self._index = index
            self.backend = "faiss-flat"

    def search(self, query: list[float], k: int) -> list[tuple[int, float]]:
        if self._index is None or not self._vectors:
            return []
        q = self.np.asarray([l2_normalize(query)], dtype=self.np.float32)
        k = min(k, len(self._vectors))
        scores, ids = self._index.search(q, k)
        return [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i >= 0]

    def save(self, path: str) -> None:
        if self._index is not None:
            self.faiss.write_index(self._index, path)

    def load(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        try:
            self._index = self.faiss.read_index(path)
            return True
        except (OSError, RuntimeError):
            return False

    def __len__(self) -> int:
        return len(self._vectors)


def create_store(kind: str, dim: int, nlist: int = 64, nprobe: int = 8):
    """返回 (store, 实际后端说明)。auto 优先 faiss → numpy → pure。"""
    requested = (kind or "auto").strip().lower()
    if requested in ("pure", "python"):
        return PureFlatStore(dim), "pure-flat"
    if requested == "numpy":
        return NumpyFlatStore(dim), "numpy-flat"
    if requested in ("faiss", "faiss-flat"):
        return FaissStore(dim, "flat", nlist, nprobe), "faiss-flat"
    if requested in ("faiss-ivf", "ivf"):
        return FaissStore(dim, "ivf", nlist, nprobe), "faiss"
    # auto
    try:
        store = FaissStore(dim, "flat", nlist, nprobe)
        return store, "faiss-flat"
    except ImportError:
        pass
    try:
        return NumpyFlatStore(dim), "numpy-flat"
    except ImportError:
        return PureFlatStore(dim), "pure-flat"


def _chunk_key(chunk) -> str:
    return f"{chunk.doc_id}#{chunk.chunk_index}"


def _embed_with_budget(provider, texts: list[str], budget_s: float | None):
    """调用 provider.embed，兼容没有 `budget_s` 参数的旧实现。

    为什么不在调用点用 try/except TypeError 兜底：那会把 embed 内部真实的 TypeError
    也当成「签名不匹配」，问题会被吞掉。这里先看签名，再决定怎么调。
    """
    if budget_s is None:
        return provider.embed(texts)
    try:
        params = inspect.signature(provider.embed).parameters
    except (TypeError, ValueError):
        return provider.embed(texts)
    if "budget_s" in params:
        return provider.embed(texts, budget_s=budget_s)
    return provider.embed(texts)


def corpus_fingerprint(chunks, model: str) -> str:
    digest = hashlib.sha256()
    digest.update(f"v{INDEX_FORMAT}|{model}".encode("utf-8"))
    for c in chunks:
        digest.update(b"\x00")
        digest.update(_chunk_key(c).encode("utf-8"))
        digest.update(b"\x01")
        digest.update((c.section + " " + c.text).encode("utf-8"))
    return digest.hexdigest()


class EmbeddingIndex:
    """把语料、provider 和向量存储绑在一起，负责构建、加载与检索。"""

    def __init__(self, chunks, provider, index_dir: str, store_kind: str = "auto",
                 nlist: int = 64, nprobe: int = 8, build_budget_s: float | None = None):
        if not chunks:
            raise ValueError("语料为空，无法建索引")
        self.chunks = chunks
        self.provider = provider
        self.index_dir = index_dir
        self.store_kind = (store_kind or "auto").strip().lower()
        self.nlist = nlist
        self.nprobe = nprobe
        self.build_budget_s = build_budget_s
        self.dim = int(getattr(provider, "dim", 0) or 0)
        self.store = None
        self.manifest: dict = {}
        self.backend = ""
        self.status = "unbuilt"
        self.build_usage: dict = {}
        self._lock = threading.Lock()
        self.manifest_path = os.path.join(index_dir, "manifest.json")
        self.vectors_path = os.path.join(index_dir, "vectors.jsonl")
        self.faiss_path = os.path.join(index_dir, "index.faiss")

    # ---------- 持久化 ----------
    def _read_manifest(self) -> dict | None:
        if not os.path.exists(self.manifest_path):
            return None
        try:
            with open(self.manifest_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _read_vectors(self) -> list[list[float]]:
        vectors: list[list[float]] = []
        with open(self.vectors_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                vectors.append([float(x) for x in row["v"]])
        return vectors

    def _write(self, vectors: list[list[float]], fingerprint: str) -> None:
        os.makedirs(self.index_dir, exist_ok=True)
        tmp_vectors = self.vectors_path + ".tmp"
        with open(tmp_vectors, "w", encoding="utf-8") as f:
            for chunk, vec in zip(self.chunks, vectors):
                f.write(json.dumps({"id": _chunk_key(chunk),
                                    "v": [round(x, 7) for x in vec]},
                                   ensure_ascii=False) + "\n")
        os.replace(tmp_vectors, self.vectors_path)

        if self.backend.startswith("faiss") and hasattr(self.store, "save"):
            tmp_index = self.faiss_path + ".tmp"
            try:
                self.store.save(tmp_index)
                os.replace(tmp_index, self.faiss_path)
            except (OSError, RuntimeError):
                pass

        manifest = {
            "format": INDEX_FORMAT,
            "model": self.provider.model,
            "dim": self.dim,
            "metric": "cosine",
            "normalized": True,
            "embedding_provider": type(self.provider).__name__,
            "store_requested": self.store_kind,
            "store": self.backend,
            "chunks": len(self.chunks),
            "fingerprint": fingerprint,
            "created_at": _now(),
            "build_usage": self.build_usage,
        }
        tmp_manifest = self.manifest_path + ".tmp"
        with open(tmp_manifest, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        os.replace(tmp_manifest, self.manifest_path)
        self.manifest = manifest

    # ---------- 构建 / 加载 ----------
    def build(self) -> dict:
        texts = [c.section + " " + c.text for c in self.chunks]
        fingerprint = corpus_fingerprint(self.chunks, self.provider.model)
        # 先探测维度，保证缓存键稳定：否则首轮用 dim=0 写缓存，下轮 dim=256 读不到，
        # 每次重建都会重新付一次 embedding 费用。
        if not self.dim:
            probe = _embed_with_budget(self.provider, ["dimension-probe"], self.build_budget_s)
            self.dim = probe.dim
        cache = EmbeddingCache(os.path.join(self.index_dir, "embeddings.cache.jsonl"),
                               self.provider.model, self.dim)
        vectors, missing = cache.get_many(texts)
        if missing:
            batch = [texts[i] for i in missing]
            result = _embed_with_budget(self.provider, batch, self.build_budget_s)
            for pos, vec in zip(missing, result.vectors):
                vectors[pos] = vec
            cache.put_many(batch, result.vectors)
            cache.save()
            self.build_usage = {"embedded": len(batch), **result.usage}
            self.dim = result.dim
        else:
            self.build_usage = {"embedded": 0, "prompt_tokens": 0, "total_tokens": 0}

        dim = self.dim or len(vectors[0])
        if any(len(v) != dim for v in vectors if v is not None):
            raise EmbeddingError("部分向量维度不一致，拒绝建索引")
        final = [v for v in vectors if v is not None]
        if len(final) != len(texts):
            raise EmbeddingError("向量数量与语料块数不一致")

        store, _ = create_store(self.store_kind, dim, self.nlist, self.nprobe)
        store.add(final)
        self.dim = dim
        self.store = store
        self.backend = getattr(store, "backend", type(store).__name__)
        self._write(final, fingerprint)
        self.status = "built"
        return self.describe()

    def load(self) -> bool:
        manifest = self._read_manifest()
        if not manifest:
            return False
        fingerprint = corpus_fingerprint(self.chunks, self.provider.model)
        if manifest.get("model") != self.provider.model:
            self.status = "rebuild:model_changed"
            return False
        if manifest.get("fingerprint") != fingerprint:
            self.status = "rebuild:corpus_changed"
            return False
        dim = int(manifest.get("dim") or 0)
        configured = int(getattr(self.provider, "dim", 0) or 0)
        if configured and dim != configured:
            raise EmbeddingError(
                f"索引维度 {dim} 与 EMBEDDING_DIM={configured} 不一致；"
                "请删除旧索引或改正维度配置"
            )
        if not dim or not os.path.exists(self.vectors_path):
            self.status = "rebuild:vectors_missing"
            return False
        try:
            vectors = self._read_vectors()
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            self.status = "rebuild:vectors_corrupt"
            return False
        if len(vectors) != len(self.chunks):
            self.status = "rebuild:count_mismatch"
            return False

        self.dim = dim
        self.provider.dim = dim
        store, requested_backend = create_store(self.store_kind, dim, self.nlist, self.nprobe)
        store.add(vectors)
        self.store = store
        self.backend = getattr(store, "backend", type(store).__name__)
        if requested_backend.startswith("faiss") and self.backend == "faiss-flat" \
                and hasattr(store, "load") and store.load(self.faiss_path):
            # 用持久化的 FAISS 索引替换刚 add 的那份，省掉重复 add；向量仍在内存里供重建
            self.backend = getattr(store, "backend", self.backend)
        self.manifest = manifest
        self.status = "loaded"
        return True

    def ensure(self) -> dict:
        with self._lock:
            try:
                if self.load():
                    return self.describe()
            except EmbeddingError:
                self.status = "rebuild:dim_mismatch"
            return self.build()

    def describe(self) -> dict:
        return {
            "status": self.status,
            "backend": self.backend,
            "model": self.provider.model,
            "dim": self.dim,
            "chunks": len(self.chunks),
            "metric": "cosine",
            "index_dir": self.index_dir,
            "build_usage": self.build_usage,
        }

    # ---------- 检索 ----------
    def search(self, query_vector: list[float], k: int) -> list[tuple[int, float]]:
        if self.store is None:
            return []
        return self.store.search(query_vector, k)
