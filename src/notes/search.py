"""笔记检索：词面 BM25 + 可选语义向量。

为什么单独做一份索引，而不是每次查询读全盘：
`index/notes.jsonl` 只存标题/标签/摘要这些元数据，正文在 `.md` 里。笔记上千篇以后
每次查询都重读一遍约 2 秒（实测 1000 篇并行重建 2.0s），交互上不可接受。所以把
「检索用文本」抽出来落一份索引，查询时只读这一份文件。

为什么文本和向量放同一个文件：
两者都以 `(mtime_ns, size)` 判定是否过期，分开两个文件就得维护两份同步状态，
而且必然出现「文本已更新、向量还是旧的」这种错配。合在一起，一次原子替换就完事。

为什么查询时增量补算，而不是保存时就建：
保存路径上已经有一次摘要（可能还有模型调用），再叠一次 embedding 网络请求，
会让「存一篇笔记」的耗时从几十毫秒变成几秒——用户点保存就卡住。
所以检索索引是**懒**的：查询时补算，且每次有上限，保证首次查询也能在预算内返回。

降级是显式的：没配 embedding provider 就只跑词面（`mode="lexical"`），
配了但调用失败就带 `degraded` 说明继续返回词面结果。**不假装有语义**。
"""

from __future__ import annotations

import array
import base64
import json
import math
import os
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

SEARCH_FILE = "search.jsonl"
TEXT_MAX = 1200
DEFAULT_SYNC_MAX = 120
BM25_K1 = 1.2
BM25_B = 0.75
# 融合权重：语义略低于词面。词面命中是硬证据，语义负责捞「换个说法」的那些，
# 但纯靠 cosine 排序容易把「同一话题但不相关」的笔记顶上来。
LEXICAL_WEIGHT = 0.55
_EMBED_BATCH = 16

_CN = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-z0-9_]{2,}")


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, "") or default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.1, float(os.environ.get(name, "") or default))
    except (TypeError, ValueError):
        return default


def search_path(home: Path) -> Path:
    return home / "index" / SEARCH_FILE


def tokenize(text: str) -> list[str]:
    """中文切 2-gram、英文按词。

    为什么不用分词器：零依赖前提下没有可靠的中文分词。2-gram 对短查询（「部署方案」
    「上次那个结论」）足够召回，代价是索引略大——一份笔记多出约一倍 token，可以接受。
    """
    lowered = (text or "").lower()
    tokens = _WORD.findall(lowered)
    for seg in _CN.findall(lowered):
        if len(seg) == 1:
            tokens.append(seg)
        else:
            tokens.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    return tokens


def encode_vector(vec: list[float]) -> str:
    """float32 + base64：1024 维从 ~15 KB 的 JSON 降到 ~5.5 KB。"""
    return base64.b64encode(array.array("f", vec).tobytes()).decode("ascii")


def decode_vector(text: str) -> list[float]:
    return array.array("f", base64.b64decode(text)).tolist()


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class BM25:
    """标准 BM25（k1=1.2, b=0.75）。笔记规模下 O(N×Q) 足够，不必建倒排。"""

    def __init__(self, docs: dict[str, list[str]]):
        self.tf: dict[str, Counter] = {}
        self.lengths: dict[str, int] = {}
        df: Counter = Counter()
        for doc_id, tokens in docs.items():
            counts = Counter(tokens)
            self.tf[doc_id] = counts
            self.lengths[doc_id] = sum(counts.values())
            for token in counts:
                df[token] += 1
        self.total = len(docs)
        self.avgdl = (sum(self.lengths.values()) / self.total) if self.total else 0.0
        # 加 1 再取对数：语料很小的时候 idf 会变成负数，负分会把命中项往下压
        self.idf = {token: math.log(1 + (self.total - n + 0.5) / (n + 0.5))
                    for token, n in df.items()}

    def scores(self, query_tokens: list[str]) -> dict[str, float]:
        wanted = Counter(query_tokens)
        if not wanted or not self.total:
            return {}
        avgdl = self.avgdl or 1.0
        out: dict[str, float] = {}
        for doc_id, counts in self.tf.items():
            length = self.lengths[doc_id] or 1
            score = 0.0
            for token, weight in wanted.items():
                freq = counts.get(token, 0)
                if not freq:
                    continue
                idf = self.idf.get(token, 0.0)
                denom = freq + BM25_K1 * (1 - BM25_B + BM25_B * length / avgdl)
                score += idf * (freq * (BM25_K1 + 1)) / denom * weight
            if score > 0:
                out[doc_id] = score
        return out


@dataclass
class Outcome:
    """一次检索的结果与自我说明。

    `mode` 与 `degraded` 是给用户看的：他要能判断「这次是语义搜的还是只搜了字面」，
    否则会以为系统「没找到」等于「没存过」。
    """

    scores: dict[str, float] = field(default_factory=dict)
    lexical: dict[str, float] = field(default_factory=dict)
    semantic: dict[str, float] = field(default_factory=dict)
    mode: str = "lexical"
    degraded: str = ""
    indexed: int = 0
    pending: int = 0
    total: int = 0

    def as_dict(self) -> dict:
        return {"mode": self.mode, "degraded": self.degraded,
                "indexed": self.indexed, "pending": self.pending, "total": self.total}


class NoteSearcher:
    """检索索引的读写与打分。

    `docs_provider(entry) -> (text, signature)` 由调用方提供：搜索层不关心
    笔记文件放在哪、markdown 怎么解析，只负责索引与打分。
    """

    def __init__(self, home: Path, docs_provider, lock=None, embed_call=None,
                 settings=None):
        self.home = home
        self.path = search_path(home)
        self._docs_provider = docs_provider
        self._lock = lock
        self._embed_call = embed_call
        self._settings = settings
        self._mutex = threading.Lock()
        self._rows: dict[str, dict] | None = None
        self._rows_stat: tuple[int, int] | None = None

    # ---- 索引读写 ----

    def _load(self) -> dict[str, dict]:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            self._rows, self._rows_stat = {}, None
            return self._rows
        signature = (stat.st_mtime_ns, stat.st_size)
        if self._rows is not None and signature == self._rows_stat:
            return self._rows
        rows: dict[str, dict] = {}
        try:
            with open(self.path, encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue      # 半行写入不该让整个检索失效
                    note_id = item.get("id")
                    if note_id:
                        rows[note_id] = item
        except OSError:
            rows = {}
        self._rows, self._rows_stat = rows, signature
        return rows

    def _flush(self, rows: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            for item in rows.values():
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        # 写索引很快（毫秒级），借用存储锁避免两个进程同时替换出半份文件
        if self._lock is not None:
            try:
                with self._lock():
                    os.replace(tmp, self.path)
            except Exception:  # noqa: BLE001 —— 拿不到锁就退化成无锁写
                os.replace(tmp, self.path)
        else:
            os.replace(tmp, self.path)
        try:
            stat = self.path.stat()
            self._rows_stat = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            self._rows_stat = None
        self._rows = rows

    # ---- 向量 ----

    def _provider(self):
        if self._settings is None:
            try:
                from ..config import load_settings
                self._settings = load_settings()
            except Exception:  # noqa: BLE001 —— 单独拷走 notes 包时没有上层配置
                return None
        try:
            from ..embeddings import make_provider
            return make_provider(self._settings)
        except Exception:  # noqa: BLE001 —— 配置不完整就当没有，不要炸掉检索
            return None

    def _embed(self, texts: list[str], budget_s: float | None):
        if self._embed_call is not None:
            try:
                return list(self._embed_call(list(texts))), ""
            except Exception as exc:  # noqa: BLE001
                return [], f"{type(exc).__name__}: {exc}"
        provider = self._provider()
        if provider is None:
            return [], ""
        try:
            result = provider.embed(texts, budget_s=budget_s)
            return result.vectors, ""
        except Exception as exc:  # noqa: BLE001 —— 降级必须带原因，不能静默
            return [], f"{type(exc).__name__}: {exc}"

    # ---- 同步 ----

    def _sync(self, wanted: list[dict], want_vec: bool, read_budget: int) -> tuple[dict, int, int, str]:
        """把候选笔记的文本/向量补齐。返回 (docs, 本次重读篇数, 仍待补数, 降级原因)。"""
        rows = self._load()
        docs: dict[str, dict] = {}
        to_read: list[dict] = []

        for entry in wanted:
            note_id = str(entry.get("id") or "")
            if not note_id:
                continue
            signature = (entry.get("mtime_ns"), entry.get("size"))
            row = rows.get(note_id)
            if row and (row.get("mtime_ns"), row.get("size")) == signature and row.get("text"):
                docs[note_id] = dict(row)
                continue
            to_read.append(entry)

        # 每次最多重读这么多篇：首次在千篇库上搜索不该把全部文件读一遍
        missing = 0
        fresh: list[str] = []
        for entry in to_read[:max(0, read_budget)]:
            note_id = str(entry["id"])
            try:
                text = self._docs_provider(entry)
            except Exception:  # noqa: BLE001 —— 单篇读失败不该让整次检索失败
                missing += 1
                continue
            if not text:
                missing += 1
                continue
            # 新读进来的条目没有 vec 字段；下面统一决定补不补
            docs[note_id] = {"id": note_id, "mtime_ns": entry.get("mtime_ns"),
                             "size": entry.get("size"), "text": text}
            fresh.append(note_id)

        degraded = ""
        pending_vec: list[tuple[dict, dict]] = []
        if want_vec and self._has_provider():
            # 缺向量的都要补：既包括刚读进来的，也包括「上次只落了文本、provider 是后来才开的」。
            # 后者容易被漏——文本命中缓存就跳过，于是开了 embedding 也永远没有向量。
            pending_vec = [(entry, docs[str(entry["id"])]) for entry in wanted
                           if str(entry.get("id")) in docs
                           and not docs[str(entry.get("id"))].get("vec")]
            fresh_set = set(fresh)
            pending_vec.sort(key=lambda pair: str(pair[0]["id"]) not in fresh_set)
            pending_vec = pending_vec[:_env_int("NOTE_SEARCH_VEC_MAX", DEFAULT_SYNC_MAX)]
            if pending_vec:
                _, degraded = self._embed_into(pending_vec, docs)

        touched = set(fresh)
        for entry, _ in pending_vec:
            touched.add(str(entry["id"]))
        if touched:
            merged = dict(rows)
            for note_id in touched:
                merged[note_id] = docs[note_id]
            # 只增改，不在这里删：wanted 是「本次候选集」，按它清理会把
            # 没被 tag/kind 过滤进来的笔记整片抹掉。残留行交给 rebuild 收。
            try:
                self._flush(merged)
            except OSError as exc:
                degraded = (degraded + "; " if degraded else "") + f"index_write_failed: {exc}"

        unvectorized = 0
        if want_vec and self._has_provider():
            # 只有「本该有向量、却没有」才算待补。没配 provider 时每条都缺向量，
            # 把它算进 pending 会让用户永远看到「N 篇待索引」，误以为索引坏了。
            unvectorized = sum(1 for entry in wanted
                               if str(entry.get("id")) in docs
                               and not docs[str(entry["id"])].get("vec"))
        pending = (len(to_read) - len(fresh)) + missing + unvectorized
        return docs, len(fresh), pending, degraded

    def _has_provider(self) -> bool:
        """有没有可用的向量通道。注入的假通道也算——测试正是靠它验证融合。"""
        return self._embed_call is not None or self._provider() is not None

    def _embed_into(self, batch: list[tuple[dict, dict]], docs: dict[str, dict],
                    budget_s: float | None = None) -> tuple[int, str]:
        """分批算向量，到时间预算就停。

        为什么要自己卡时间：`provider.embed()` 的 wall_clock 是「最多等多久」而不是
        「最多花多久」，一次塞 120 篇进去只会整批超时，然后一篇都拿不到。
        小批推进 + 累计计时，最坏情况是这次只补了一部分，剩下的下次查询继续。
        """
        if budget_s is None:
            budget_s = _env_float("NOTE_SEARCH_EMBED_BUDGET_S", 20.0)
        deadline = time.monotonic() + max(1.0, budget_s)
        done = 0
        degraded = ""
        for start in range(0, len(batch), _EMBED_BATCH):
            if time.monotonic() >= deadline:
                break
            chunk = batch[start:start + _EMBED_BATCH]
            vectors, error = self._embed([doc["text"] for _, doc in chunk], budget_s=None)
            if error:
                degraded = f"embedding_failed: {error}"
                break
            for (entry, _), vector in zip(chunk, vectors):
                docs[str(entry["id"])]["vec"] = encode_vector(_normalize(vector))
                docs[str(entry["id"])]["dim"] = len(vector)
            done += len(chunk)
        return done, degraded

    # ---- 检索 ----

    def search(self, query: str, wanted: list[dict], semantic: str = "auto",
               embed_budget: int | None = None) -> Outcome:
        query = (query or "").strip()
        if not wanted:
            return Outcome()
        budget = _env_int("NOTE_SEARCH_SYNC_MAX", DEFAULT_SYNC_MAX) if embed_budget is None else embed_budget
        want_vec = semantic != "off"

        with self._mutex:
            docs, indexed, pending, degraded = self._sync(wanted, want_vec, budget)

        tokens = tokenize(query)
        lexical = BM25({note_id: tokenize(row.get("text") or "") for note_id, row in docs.items()}) \
            .scores(tokens) if tokens else {}
        semantic_scores: dict[str, float] = {}

        if want_vec and tokens:
            vectors = [row for row in docs.values() if row.get("vec")]
            query_vectors, error = self._embed([query], None)
            if error and not degraded:
                degraded = f"embedding_failed: {error}"
            if query_vectors and vectors:
                query_vec = _normalize(query_vectors[0])
                for row in vectors:
                    vec = decode_vector(row["vec"])
                    if len(vec) != len(query_vec):
                        continue      # 换了模型/维度：这条先不参与语义排序
                    semantic_scores[row["id"]] = sum(a * b for a, b in zip(query_vec, vec))

        mode = "hybrid" if semantic_scores else "lexical"
        scores = _fuse(lexical, semantic_scores)
        return Outcome(scores=scores, lexical=lexical, semantic=semantic_scores, mode=mode,
                       degraded=degraded, indexed=indexed, pending=pending, total=len(docs))

    def rebuild(self, wanted: list[dict], want_vec: bool = True) -> tuple[int, str, int]:
        """全量重建：把已有索引作废，逐条重算。`note rebuild` 命令走这里。

        只有这里会真正清理残留行——它拿到的 `wanted` 是全量笔记，而不是某次查询的候选集。

        返回第三个值是「读不出来、被跳过」的篇数。原来这里直接 `continue`，
        用户在结果里看不到「有 3 篇没进索引」，下次搜索它们永远不出现，
        而提示里一切正常——违反「失败必须可见」。
        """
        rows: dict[str, dict] = {}
        stale: list[tuple[dict, dict]] = []
        skipped = 0
        for entry in wanted:
            try:
                text = self._docs_provider(entry)
            except Exception:  # noqa: BLE001 —— 单篇坏文件不该让整次重建失败
                skipped += 1
                continue
            if not text:
                skipped += 1
                continue
            note_id = str(entry["id"])
            rows[note_id] = {"id": note_id, "mtime_ns": entry.get("mtime_ns"),
                             "size": entry.get("size"), "text": text}
            stale.append((entry, rows[note_id]))
        degraded = ""
        if want_vec and stale:
            # 重建是显式动作，预算按建库口径放宽（默认 600s）
            _, degraded = self._embed_into(stale, rows,
                                           budget_s=_env_float("NOTE_SEARCH_REBUILD_BUDGET_S", 600.0))
        self._flush(rows)
        return len(rows), degraded, skipped


def _fuse(lexical: dict[str, float], semantic: dict[str, float]) -> dict[str, float]:
    """两路分数各自按最大值归一后加权求和。

    不归一直接相加是不行的：BM25 分数可以到十几，cosine 最大只有 1，词面会把语义完全压死。
    没有语义分的条目（新存的、还没索引的）直接用语面归一值参与：给它打个折会让
    「刚存完就搜不到」——那是最容易被当成 bug 的体验。
    """
    if not semantic:
        return dict(lexical)
    top_l = max(lexical.values(), default=0.0) or 1.0
    top_s = max((abs(value) for value in semantic.values()), default=0.0) or 1.0
    merged: dict[str, float] = {}
    for note_id in set(lexical) | set(semantic):
        lexical_norm = lexical.get(note_id, 0.0) / top_l
        if note_id in semantic:
            merged[note_id] = (LEXICAL_WEIGHT * lexical_norm
                               + (1 - LEXICAL_WEIGHT) * semantic[note_id] / top_s)
        else:
            merged[note_id] = lexical_norm
    return merged
