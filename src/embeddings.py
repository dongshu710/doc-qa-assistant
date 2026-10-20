"""真 embedding 接入层：OpenAI 兼容 `/embeddings` 协议（bge / OpenAI 同协议）。

设计要点：
1. **不绑定厂商**：只依赖 `POST {base_url}/embeddings` 这一条事实标准。
   BGE 用 TEI / Xinference / vLLM / Ollama 部署后都暴露同一路径，OpenAI 亦然。
2. **维度不写死**：首次调用探测维度，写进索引 manifest；配置了
   `EMBEDDING_DIM` 就做一致性校验，不一致直接报错，绝不静默截断/补零。
3. **超时与重试显式**：连接/读取超时、429/5xx 指数退避 + 抖动、总墙钟上限，
   全部来自配置；失败抛 `EmbeddingError`，由检索层降级到 BM25。
4. **按批请求**：`EMBEDDING_BATCH` 控制单批条数，降低小文档集的请求数；
   每批都校验返回条数与 index，防止服务端乱序或缺条导致向量错位。
5. **缓存**：`EmbeddingCache` 以 `model|dim|text` 的哈希为键落盘，
   知识库小改时只重算变化的块，迁移/重建不需要重新付费。

诚实说明：本模块不内置任何本地模型权重。要在本机跑 bge，请先用
TEI / Xinference / Ollama 起一个 OpenAI 兼容端点，再把 `EMBEDDING_BASE_URL`
指过去；这样进程内不需要 torch，部署体积和冷启动都可控。
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse


class EmbeddingError(RuntimeError):
    """embedding 调用失败（网络 / 协议 / 维度不一致）。"""


class EmbeddingUnavailable(EmbeddingError):
    """未配置 provider，或配置不完整。"""


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    dim: int
    usage: dict = field(default_factory=dict)
    latency_ms: float = 0.0


def _is_loopback(host: str) -> bool:
    host = (host or "").lower()
    return host in ("localhost", "::1", "[::1]") or host.startswith("127.")


def _post_json(url: str, payload: dict, headers: dict, timeout_s: float,
               opener=None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    open_fn = opener.open if opener is not None else urllib.request.urlopen
    with open_fn(req, timeout=timeout_s) as resp:
        raw = resp.read()
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EmbeddingError(f"embedding 响应不是合法 JSON: {exc}") from exc


class OpenAIEmbeddingProvider:
    """OpenAI 兼容 embeddings 客户端（bge 同协议）。"""

    def __init__(self, base_url: str, model: str, api_key: str = "", dim: int = 0,
                 batch_size: int = 16, timeout_s: float = 8.0, max_retries: int = 2,
                 backoff_base_s: float = 0.5, backoff_max_s: float = 4.0,
                 wall_clock_s: float = 30.0, max_chars: int = 2000):
        self.base_url = (base_url or "").rstrip("/")
        self.model = (model or "").strip()
        self.api_key = api_key or ""
        self.dim = max(0, int(dim or 0))
        self.batch_size = max(1, int(batch_size or 1))
        self.timeout_s = max(0.5, float(timeout_s or 8.0))
        self.max_retries = max(0, int(max_retries or 0))
        self.backoff_base_s = max(0.0, float(backoff_base_s))
        self.backoff_max_s = max(self.backoff_base_s, float(backoff_max_s))
        self.wall_clock_s = max(self.timeout_s, float(wall_clock_s or 30.0))
        self.max_chars = max(32, int(max_chars or 2000))
        self.last_usage: dict = {}
        self._lock = threading.Lock()
        # 本地推理端点（TEI/Xinference/Ollama）不应走公司代理：代理会把
        # 127.0.0.1 当成外网转发，得到 502，且错误信息与真实原因无关。
        host = urlparse(self.base_url).hostname or ""
        self._opener = (urllib.request.build_opener(urllib.request.ProxyHandler({}))
                        if _is_loopback(host) else None)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/embeddings"

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _retry_after(self, exc: urllib.error.HTTPError) -> float | None:
        raw = exc.headers.get("Retry-After") if exc.headers else None
        if not raw:
            return None
        try:
            return max(0.0, float(str(raw).strip()))
        except ValueError:
            return None

    def _embed_batch(self, batch: list[str], deadline: float) -> tuple[list[list[float]], dict]:
        payload = {"model": self.model, "input": batch}
        # 只在显式配置维度时传 dimensions（部分兼容服务不接受该字段）
        if self.dim > 0:
            payload["dimensions"] = self.dim

        attempt = 0
        while True:
            attempted_at = time.time()
            if attempted_at >= deadline:
                raise EmbeddingError(f"embedding 超出墙钟预算 {self.wall_clock_s}s")
            try:
                data = _post_json(self.endpoint, payload, self._headers(), self.timeout_s,
                                  opener=self._opener)
                return self._parse(data, len(batch))
            except urllib.error.HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt >= self.max_retries:
                    detail = ""
                    try:
                        detail = exc.read().decode("utf-8", "replace")[:300]
                    except OSError:
                        pass
                    raise EmbeddingError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
                wait = self._retry_after(exc)
                if wait is None:
                    wait = self._backoff(attempt)
                self._sleep(wait, deadline)
                attempt += 1
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt >= self.max_retries:
                    raise EmbeddingError(f"连接失败: {exc}") from exc
                self._sleep(self._backoff(attempt), deadline)
                attempt += 1

    def _backoff(self, attempt: int) -> float:
        raw = self.backoff_base_s * (2 ** attempt)
        jitter = 0.5 + random.random()  # 全抖动：避免多实例重试同步
        return min(self.backoff_max_s, raw * jitter)

    def _sleep(self, seconds: float, deadline: float) -> None:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise EmbeddingError(f"embedding 超出墙钟预算 {self.wall_clock_s}s")
        time.sleep(min(seconds, remaining))

    def _parse(self, data: dict, expected: int) -> tuple[list[list[float]], dict]:
        if not isinstance(data, dict):
            raise EmbeddingError("embedding 响应结构异常：顶层不是对象")
        items = data.get("data")
        if not isinstance(items, list) or len(items) != expected:
            got = len(items) if isinstance(items, list) else "非数组"
            raise EmbeddingError(f"embedding 返回条数不匹配：期望 {expected}，实际 {got}")
        ordered: list[list[float] | None] = [None] * expected
        dim = 0
        for pos, item in enumerate(items):
            if not isinstance(item, dict):
                raise EmbeddingError("embedding 响应元素不是对象")
            idx = item.get("index", pos)
            if not isinstance(idx, int) or not 0 <= idx < expected:
                raise EmbeddingError(f"embedding 返回非法 index: {idx!r}")
            vec = item.get("embedding")
            if not isinstance(vec, list) or not vec:
                raise EmbeddingError("embedding 向量为空")
            if dim == 0:
                dim = len(vec)
            elif len(vec) != dim:
                raise EmbeddingError(f"同一批次向量维度不一致：{dim} vs {len(vec)}")
            clean: list[float] = []
            for value in vec:
                try:
                    clean.append(float(value))
                except (TypeError, ValueError) as exc:
                    raise EmbeddingError("embedding 含非数值元素") from exc
            ordered[idx] = clean
        if any(v is None for v in ordered):
            raise EmbeddingError("embedding 返回缺少部分 index")
        vectors = [v for v in ordered if v is not None]
        if self.dim > 0 and dim != self.dim:
            raise EmbeddingError(
                f"维度不一致：配置 EMBEDDING_DIM={self.dim}，模型实际返回 {dim}。"
                "请核对模型名，或把 EMBEDDING_DIM 置空让系统自动探测。"
            )
        self.dim = dim
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return vectors, {
            "prompt_tokens": int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or usage.get("prompt_tokens") or 0),
        }

    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not self.configured:
            raise EmbeddingUnavailable("EMBEDDING_BASE_URL / EMBEDDING_MODEL 未配置")
        cleaned = [(t or "").replace("\x00", " ").strip()[: self.max_chars] for t in texts]
        if not cleaned:
            return EmbeddingResult([], self.model, self.dim, {}, 0.0)

        started = time.time()
        deadline = started + self.wall_clock_s
        vectors: list[list[float]] = []
        usage = {"prompt_tokens": 0, "total_tokens": 0}
        for i in range(0, len(cleaned), self.batch_size):
            batch = cleaned[i:i + self.batch_size]
            vecs, used = self._embed_batch(batch, deadline)
            vectors.extend(vecs)
            usage["prompt_tokens"] += int(used.get("prompt_tokens") or 0)
            usage["total_tokens"] += int(used.get("total_tokens") or 0)
        result = EmbeddingResult(vectors, self.model, self.dim, usage,
                                 round((time.time() - started) * 1000, 1))
        with self._lock:
            self.last_usage = usage
        return result


class EmbeddingCache:
    """按内容哈希缓存向量；只缓存成功结果，失败不落盘。"""

    def __init__(self, path: str, model: str, dim: int):
        self.path = path
        self.model = model
        self.dim = dim
        self._data: dict[str, list[float]] = {}
        self._dirty = False
        self._lock = threading.Lock()
        self._load()

    def _key(self, text: str) -> str:
        raw = f"{self.model}|{self.dim}|{text}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    key = row.get("k")
                    vec = row.get("v")
                    if isinstance(key, str) and isinstance(vec, list) and vec:
                        self._data[key] = vec
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def get_many(self, texts: list[str]) -> tuple[list[list[float] | None], list[int]]:
        with self._lock:
            vectors: list[list[float] | None] = []
            missing: list[int] = []
            for i, text in enumerate(texts):
                vec = self._data.get(self._key(text))
                vectors.append(vec)
                if vec is None:
                    missing.append(i)
            return vectors, missing

    def put_many(self, texts: list[str], vectors: list[list[float]]) -> None:
        with self._lock:
            for text, vec in zip(texts, vectors):
                self._data[self._key(text)] = vec
            self._dirty = True

    def save(self) -> None:
        if not self.path or not self._dirty:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            with self._lock, open(tmp, "w", encoding="utf-8") as f:
                for key, vec in self._data.items():
                    f.write(json.dumps({"k": key, "v": vec}, ensure_ascii=False) + "\n")
            os.replace(tmp, self.path)
            self._dirty = False
        except OSError:
            # 缓存写失败只影响下次重建成本，不影响本次检索
            pass


def make_provider(settings):
    """按配置构造 provider；未配置返回 None（调用方回退词法检索）。"""
    kind = (getattr(settings, "embedding_provider", "none") or "none").strip().lower()
    if kind in ("", "none", "off", "disabled"):
        return None
    if kind not in ("openai", "bge"):
        raise EmbeddingUnavailable(f"未知 EMBEDDING_PROVIDER={kind}（支持 none / openai / bge）")
    base = (getattr(settings, "embedding_base_url", "") or "").strip()
    model = (getattr(settings, "embedding_model", "") or "").strip()
    if not base or not model:
        raise EmbeddingUnavailable(
            "EMBEDDING_PROVIDER 已开启，但 EMBEDDING_BASE_URL / EMBEDDING_MODEL 为空"
        )
    return OpenAIEmbeddingProvider(
        base_url=base,
        model=model,
        api_key=getattr(settings, "embedding_api_key", "") or "",
        dim=getattr(settings, "embedding_dim", 0),
        batch_size=getattr(settings, "embedding_batch", 16),
        timeout_s=getattr(settings, "embedding_timeout_s", 8.0),
        max_retries=getattr(settings, "embedding_max_retries", 2),
        backoff_base_s=getattr(settings, "embedding_backoff_base_s", 0.5),
        backoff_max_s=getattr(settings, "embedding_backoff_max_s", 4.0),
        wall_clock_s=getattr(settings, "embedding_wall_clock_s", 30.0),
    )
