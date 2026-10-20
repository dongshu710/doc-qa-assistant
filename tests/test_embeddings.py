"""embedding 接入、索引构建/加载与降级路径测试。

用法：
    python tests/test_embeddings.py          # 零依赖后端
    <venv>/python tests/test_embeddings.py   # 装了 numpy/faiss 时额外验证 FAISS

不访问公网：HTTP 部分用本地假 `/v1/embeddings` 服务，便于验证批大小、
返回乱序、429 重试与维度校验。
"""
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.chunking import Chunk  # noqa: E402
from src.embeddings import (  # noqa: E402
    EmbeddingError,
    EmbeddingResult,
    OpenAIEmbeddingProvider,
)
from src.retriever import EmbeddingRetriever  # noqa: E402
from src.vector_store import EmbeddingIndex  # noqa: E402


class FakeProvider:
    """字符袋向量：确定性、无需网络，用来测索引与重排。"""

    def __init__(self, dim: int = 16, model: str = "fake-bge"):
        self.model = model
        self.dim = dim
        self.calls = 0
        self.fail = False

    def embed(self, texts):
        if self.fail:
            raise EmbeddingError("fake failure")
        vectors = []
        for text in texts:
            vec = [0.0] * self.dim
            for ch in text:
                vec[ord(ch) % self.dim] += 1.0
            vectors.append(vec)
        self.calls += 1
        return EmbeddingResult(vectors, self.model, self.dim, {"total_tokens": len(texts) * 3})


def make_chunks():
    return [
        Chunk("a", "大额存单", "转让", "大额存单可以转让，需通过发行机构渠道办理。", 0),
        Chunk("b", "风险测评", "等级", "客户风险承受能力等级分为五级。", 1),
        Chunk("c", "理财", "起购", "稳盈系列起购金额为一万元。", 2),
    ]


class EmbedHandler(BaseHTTPRequestHandler):
    state = {"calls": 0, "fail_once": False, "bad_count": False, "order": "reverse"}

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        EmbedHandler.state["calls"] += 1
        if EmbedHandler.state["fail_once"] and EmbedHandler.state["calls"] == 1:
            body = b'{"error":"slow down"}'
            self.send_response(429)
            self.send_header("Retry-After", "0")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        texts = payload.get("input") or []
        data = []
        for i, text in enumerate(texts):
            vec = [0.1 * (i + 1), 0.2, 0.3, 0.4]
            data.append({"object": "embedding", "index": i, "embedding": vec})
        if EmbedHandler.state["order"] == "reverse":
            data = list(reversed(data))
        if EmbedHandler.state["bad_count"]:
            data = data[:-1]
        body = json.dumps({"object": "list", "data": data, "model": payload.get("model"),
                           "usage": {"prompt_tokens": len(texts) * 2,
                                     "total_tokens": len(texts) * 2}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def test_http_provider():
    EmbedHandler.state.update({"calls": 0, "fail_once": True, "bad_count": False})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), EmbedHandler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        provider = OpenAIEmbeddingProvider(
            f"http://127.0.0.1:{port}/v1", "bge-test", dim=0, batch_size=2,
            timeout_s=2, max_retries=2, backoff_base_s=0.01, backoff_max_s=0.02,
        )
        texts = [f"文本{i}" for i in range(5)]
        result = provider.embed(texts)
        assert len(result.vectors) == 5, len(result.vectors)
        assert result.dim == 4, result.dim
        # 429 重试后仍只有 3 个成功批次 + 1 次失败
        assert EmbedHandler.state["calls"] == 4, EmbedHandler.state["calls"]
        assert result.usage["total_tokens"] == 10
        # 返回乱序但带 index，必须按 index 还原：第 2 条应为 [0.2,0.2,0.3,0.4]
        assert abs(result.vectors[1][0] - 0.2) < 1e-9, result.vectors[1]
        print("http provider OK (batch/retry/order/usage)")

        EmbedHandler.state["bad_count"] = True
        try:
            provider.embed(["x"])
        except EmbeddingError as exc:
            assert "条数不匹配" in str(exc)
            print("bad response rejected OK")
        else:
            raise AssertionError("缺条响应必须报错，不能静默错位")
    finally:
        httpd.shutdown()


def test_index(tmp: Path):
    chunks = make_chunks()
    provider = FakeProvider()
    index_dir = str(tmp / "idx")
    index = EmbeddingIndex(chunks, provider, index_dir, store_kind="pure")
    status = index.ensure()
    assert status["status"] == "built" and status["dim"] == 16, status
    assert status["backend"] == "pure-flat", status
    assert (Path(index_dir) / "manifest.json").exists()

    qv = provider.embed(["大额存单转让"]).vectors[0]
    hits = index.search(qv, 2)
    assert hits and chunks[hits[0][0]].doc_id == "a", hits
    print("index build/search OK")

    calls = provider.calls
    reloaded = EmbeddingIndex(chunks, provider, index_dir, store_kind="pure")
    assert reloaded.load(), reloaded.status
    assert reloaded.status == "loaded"
    assert provider.calls == calls, "加载不应重新 embedding"
    hits2 = reloaded.search(qv, 1)
    assert hits2[0][0] == hits[0][0]
    print("index reload OK (no re-embed)")

    changed = chunks + [Chunk("d", "新文档", "概述", "新增内容", 3)]
    stale = EmbeddingIndex(changed, provider, index_dir, store_kind="pure")
    assert not stale.load() and stale.status == "rebuild:corpus_changed", stale.status
    print("corpus fingerprint invalidation OK")

    other_model = FakeProvider(model="fake-bge-v2")
    assert not EmbeddingIndex(chunks, other_model, index_dir, store_kind="pure").load()
    print("model change invalidation OK")


def test_dim_mismatch(tmp: Path):
    chunks = make_chunks()
    index_dir = str(tmp / "dim")
    EmbeddingIndex(chunks, FakeProvider(dim=16), index_dir, store_kind="pure").ensure()
    wrong = FakeProvider(dim=8)
    wrong.model = "fake-bge"  # 模型名相同、维度不同，模拟换版本
    try:
        EmbeddingIndex(chunks, wrong, index_dir, store_kind="pure").load()
    except EmbeddingError as exc:
        assert "维度" in str(exc)
        print("dimension mismatch rejected OK")
    else:
        raise AssertionError("维度不一致必须报错")


def test_faiss(tmp: Path):
    try:
        import faiss  # noqa: F401
    except ImportError:
        print("faiss not installed, skip FAISS backend")
        return
    chunks = make_chunks()
    provider = FakeProvider()
    index = EmbeddingIndex(chunks, provider, str(tmp / "faiss"), store_kind="faiss")
    status = index.ensure()
    assert status["backend"].startswith("faiss"), status
    qv = provider.embed(["大额存单转让"]).vectors[0]
    hits = index.search(qv, 1)
    assert chunks[hits[0][0]].doc_id == "a", hits
    assert (Path(tmp / "faiss") / "index.faiss").exists()
    print("faiss backend OK:", status["backend"])


def test_retriever(tmp: Path):
    chunks = make_chunks()
    provider = FakeProvider()
    retriever = EmbeddingRetriever(chunks, provider, str(tmp / "ret"), store_kind="pure")
    calls = provider.calls
    hits = retriever.search("大额存单可以转让吗", 2)
    assert hits and hits[0][0].doc_id == "a", hits
    assert retriever.last_error is None
    assert provider.calls == calls + 1, "一次查询只应 embedding 一次"

    retriever.search("大额存单可以转让吗", 2)
    assert provider.calls == calls + 1, "重复查询应命中 LRU 缓存"
    print("retriever + query cache OK")

    provider.fail = True
    # 换一个未缓存的问题，才会真正触发 embedding 调用失败
    hits = retriever.search("风险等级怎么划分", 2)
    assert hits, "embedding 失败时应回退 BM25，而不是返回空"
    assert retriever.last_error and "fake failure" in retriever.last_error
    assert retriever.describe()["degraded"]
    print("embedding failure fallback OK")


if __name__ == "__main__":
    test_http_provider()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        test_index(root)
        test_dim_mismatch(root)
        test_faiss(root)
        test_retriever(root)
    print("ALL EMBEDDING TESTS PASSED")
