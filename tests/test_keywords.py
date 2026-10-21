"""关键词直出：抽取、命中、API 增强、缓存复用与「命中不调用 API」的硬验证。

最后一条是关键：用假模型端点统计请求数，命中间答前后计数必须不变。
只断言语义（「没调模型」）而不数请求，等于没验证。
"""
import json
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.chunking import load_corpus  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.keywords import KeywordIndex  # noqa: E402
from src.pipeline import RAGPipeline  # noqa: E402

DEMO = ROOT / "data" / "demo"


@contextmanager
def env(**values):
    old = {k: os.environ.get(k) for k in values}
    os.environ.update({k: str(v) for k, v in values.items()})
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeLLM(BaseHTTPRequestHandler):
    calls: list[dict] = []
    mode = "json"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        FakeLLM.calls.append({"path": self.path, "payload": payload})
        if FakeLLM.mode == "garbage":
            content = "这不是 JSON，模型跑偏了。"
        else:
            content = json.dumps({
                "summary": "小a的饮食、作息与爱好",
                "keywords": [
                    {"term": "拿铁", "aliases": ["咖啡"]},
                    {"term": "城市之光书店", "aliases": ["书店"]},
                    {"term": "游泳", "aliases": ["泳池"]},
                    {"term": "香菜", "aliases": ["芫荽"]},
                ],
            }, ensure_ascii=False)
        body = json.dumps({
            "choices": [{"message": {"content": content}}],
            "usage": {"total_tokens": 42},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def test_extraction() -> None:
    chunks = load_corpus(str(DEMO))
    with tempfile.TemporaryDirectory() as tmp:
        index = KeywordIndex(chunks, load_settings(), os.path.join(tmp, "kw.json"))
        detail = index.ensure(enrich=False)
        assert detail["docs"] == 1, detail
        assert detail["direct"] >= 15, detail
        assert detail["by_kind"]["item"] >= 10, detail

        cases = {
            "我爱吃什么": "爱吃的食物",
            "我不吃什么": "不吃的食物",
            "我有什么忌口": "忌口",
            "我几点起床": "起床时间",
            "我养了什么宠物": "宠物",
            "我有什么爱好": "爱好",
        }
        for query, term in cases.items():
            hits = index.match(query)
            assert hits, f"{query} 应命中"
            assert term in [h.entry.term for h in hits], (query, [(h.entry.term, h.entry.kind) for h in hits])

        for query in ("今天天气怎么样", "帮我订一张机票", "什么是净值型理财"):
            assert not index.match(query), f"{query} 不应触发直出"

        # 只认结构化条目：章节名不触发
        assert all(h.entry.kind != "heading" for h in index.match("饮食偏好"))
        print("extraction & match OK")


def test_finance_no_hijack() -> None:
    """制度类文档的常规问题不能被关键词截胡，否则会绕开引用生成。"""
    chunks = load_corpus(str(ROOT / "data" / "knowledge"))
    with tempfile.TemporaryDirectory() as tmp:
        index = KeywordIndex(chunks, load_settings(), os.path.join(tmp, "kw.json"))
        index.ensure(enrich=False)
        for query in ("稳盈系列的起购金额是多少", "大额存单可以转让吗",
                      "理财产品风险等级分为几档", "R3 及以上产品首次购买有什么要求"):
            hits = index.match(query)
            assert not hits, (query, [(h.entry.term, h.entry.kind) for h in hits])
        print("finance policy questions stay on RAG OK")


def test_llm_enrichment_and_cache(tmp: str, base_url: str) -> None:
    chunks = load_corpus(str(DEMO))
    FakeLLM.calls.clear()
    with env(KEYWORD_LLM="on", LLM_API_KEY="test-key", LLM_BASE_URL=base_url, LLM_MODEL="fake"):
        index = KeywordIndex(chunks, load_settings(), os.path.join(tmp, "kw.json"))
        detail = index.ensure(enrich=True)
        assert len(FakeLLM.calls) == 1, FakeLLM.calls
        assert detail["by_kind"]["llm"] >= 1, detail
        doc_id = chunks[0].doc_id
        assert index.docs[doc_id]["summary"] == "小a的饮食、作息与爱好"
        assert index.docs[doc_id]["llm"] is True

        # 同义词来自模型，句子必须来自原文
        hits = index.match("我想喝咖啡")
        assert hits and hits[0].entry.term == "拿铁", [(h.entry.term, h.score) for h in hits]
        assert hits[0].entry.snippet.startswith("爱吃的食物"), hits[0].entry.snippet
        assert "咖啡" not in hits[0].entry.snippet

        # 语料没变就复用缓存，不再打模型
        again = KeywordIndex(chunks, load_settings(), os.path.join(tmp, "kw.json"))
        again.ensure(enrich=True)
        assert len(FakeLLM.calls) == 1, "相同语料不应重复调用模型"
    print("llm enrichment, alias merge, snippet anchoring, cache reuse OK")


def test_llm_failure_falls_back(base_url: str) -> None:
    FakeLLM.mode = "garbage"
    chunks = load_corpus(str(DEMO))
    with tempfile.TemporaryDirectory() as tmp, env(
            KEYWORD_LLM="on", LLM_API_KEY="test-key", LLM_BASE_URL=base_url, LLM_MODEL="fake"):
        index = KeywordIndex(chunks, load_settings(), os.path.join(tmp, "kw.json"))
        detail = index.ensure(enrich=True)
        assert detail["entries"] >= 15, detail
        assert detail["llm_docs"] == 0, detail
        assert index.docs[chunks[0].doc_id]["error"], "解析失败必须记录原因"
        assert index.match("我爱吃什么"), "模型失败不应影响本地关键词"
    FakeLLM.mode = "json"
    print("llm failure fallback OK")


def test_pipeline_no_api(base_url: str) -> None:
    FakeLLM.calls.clear()
    with tempfile.TemporaryDirectory() as tmp, env(
            KEYWORD_LLM="on", KEYWORD_INDEX=os.path.join(tmp, "kw.json"),
            LLM_API_KEY="test-key", LLM_BASE_URL=base_url, LLM_MODEL="fake",
            QUERY_EXPANSION="off", RETRIEVAL="bm25", MIN_SCORE="0"):
        pipe = RAGPipeline(str(DEMO))
        assert len(FakeLLM.calls) == 0, "启动阶段不应调用模型"

        before = len(FakeLLM.calls)
        result = pipe.ask("我不吃香菜")
        assert result["path"] == "keyword", result.get("path")
        assert result["mode"] == "keyword_local", result.get("mode")
        assert result["api_called"] is False, result.get("api_called")
        assert len(FakeLLM.calls) == before, "命中后不得调用任何模型接口"
        assert "不吃的食物" in result["answer"], result["answer"]
        assert result["citations"][0]["title"] == "小a的生活习惯"
        assert result["citation_coverage"] == 1.0
        assert result["keyword_terms"], result

        # 未命中走检索生成：这次应当真的调用模型
        fallback = pipe.ask("今天天气怎么样")
        assert fallback["path"] == "rag", fallback.get("path")
        assert fallback["api_called"] is True, fallback
        assert len(FakeLLM.calls) > before, "回退路径应调用模型"

        # 重建索引才会做模型整理，且只对未整理过的文档
        calls_before = len(FakeLLM.calls)
        detail = pipe.rebuild_keywords(enrich=True)
        assert detail["llm"] is True, detail
        assert len(FakeLLM.calls) == calls_before + 1, FakeLLM.calls
        assert pipe.keywords.match("我想喝咖啡"), "重建后应带上同义词"
    print("pipeline keyword-first, API bypass, fallback, rebuild OK")


def main() -> None:
    if not (DEMO / "小a的生活习惯.md").exists():
        raise SystemExit(f"缺少演示文档: {DEMO}")
    test_extraction()
    test_finance_no_hijack()

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeLLM)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{port}/v1"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            test_llm_enrichment_and_cache(tmp, base_url)
        test_llm_failure_falls_back(base_url)
        test_pipeline_no_api(base_url)
    finally:
        server.shutdown()
        server.server_close()
    print("ALL KEYWORD TESTS PASSED")


if __name__ == "__main__":
    main()
