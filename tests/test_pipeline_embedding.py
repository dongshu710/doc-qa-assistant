"""pipeline 级集成：真 embedding 检索、索引复用、服务不可达时降级。

用法：python tests/test_pipeline_embedding.py
不访问公网：本地假 `/v1/embeddings`，返回字符二元组哈希向量（确定性）。
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline import RAGPipeline  # noqa: E402

DIM = 256
CALLS = {"embed": 0}


class EmbedHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        texts = payload.get("input") or []
        CALLS["embed"] += 1
        data = []
        for i, text in enumerate(texts):
            vec = [0.0] * DIM
            for j in range(len(text) - 1):
                code = (ord(text[j]) * 31 + ord(text[j + 1])) % DIM
                vec[code] += 1.0
            data.append({"object": "embedding", "index": i, "embedding": vec})
        body = json.dumps({"data": data, "model": payload.get("model"),
                           "usage": {"prompt_tokens": len(texts) * 4,
                                     "total_tokens": len(texts) * 4}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def env_for(port: int, index_dir: Path) -> dict:
    return {
        "RETRIEVAL": "embedding",
        "EMBEDDING_PROVIDER": "openai",
        "EMBEDDING_BASE_URL": f"http://127.0.0.1:{port}/v1",
        "EMBEDDING_MODEL": "fake-bge",
        "EMBEDDING_DIM": "0",
        "EMBEDDING_BATCH": "16",
        "EMBEDDING_TIMEOUT_S": "3",
        "EMBEDDING_MAX_RETRIES": "0",
        "EMBEDDING_INDEX_DIR": str(index_dir),
        "VECTOR_STORE": "pure",
        "QUERY_EXPANSION": "off",
        "LLM_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
    }


def main() -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), EmbedHandler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            index_dir = Path(tmp) / "index"
            with mock.patch.dict(os.environ, env_for(port, index_dir), clear=False):
                os.environ.pop("LLM_API_KEY", None)
                os.environ.pop("DEEPSEEK_API_KEY", None)

                pipe = RAGPipeline(str(ROOT / "data" / "knowledge"))
                detail = pipe.retrieval_detail
                assert detail["mode"] == "embedding", detail
                assert detail["index_status"] == "built", detail
                assert detail["dim"] == DIM, detail
                print("pipeline embedding index built OK:", detail["backend"], detail["dim"])

                result = pipe.ask("大额存单可以转让吗")
                assert result["retrieval_mode"] == "embedding", result
                assert result["retrieved"], result
                assert result.get("embedding_tokens", 0) > 0, result
                print("ask with embedding OK:", result["behavior"],
                      result["retrieval_score"], result["embedding_tokens"], "tokens")

                calls = CALLS["embed"]
                pipe2 = RAGPipeline(str(ROOT / "data" / "knowledge"))
                assert pipe2.retrieval_detail["index_status"] == "loaded", pipe2.retrieval_detail
                assert CALLS["embed"] == calls, "已有索引时启动不应重新 embedding"
                print("index reuse on restart OK")

                # 停掉 embedding 服务：索引还能加载，但查询必须降级到词法检索
                httpd.shutdown()
                httpd.server_close()
                pipe3 = RAGPipeline(str(ROOT / "data" / "knowledge"))
                detail3 = pipe3.retrieval_detail
                assert detail3["mode"] == "embedding" and detail3["index_status"] == "loaded", detail3
                result3 = pipe3.ask("大额存单可以转让吗")
                assert result3["retrieval_mode"] == "embedding", result3
                assert result3["degraded"] is True, result3
                assert result3["degrade_reason"] == "embedding_error", result3
                assert result3["retrieval_error"], result3
                print("query-time embedding failure degraded OK:",
                      result3["retrieval_error"][:60])

                # 没有索引 + 服务不可达：启动时回退零依赖检索，且原因可见
                with mock.patch.dict(os.environ,
                                     {"EMBEDDING_INDEX_DIR": str(Path(tmp) / "empty_index")},
                                     clear=False):
                    pipe4 = RAGPipeline(str(ROOT / "data" / "knowledge"))
                    detail4 = pipe4.retrieval_detail
                    assert detail4["mode"] == "vector", detail4
                    assert detail4["fallback_error"], detail4
                    assert pipe4.ask("大额存单可以转让吗")["behavior"] in ("answer", "no_answer")
                    print("cold-start fallback OK:", detail4["fallback_error"][:60])
    finally:
        try:
            httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
    print("ALL PIPELINE EMBEDDING TESTS PASSED")


if __name__ == "__main__":
    main()
