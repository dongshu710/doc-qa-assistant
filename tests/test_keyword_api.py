"""关键词能力的 HTTP 冒烟：知识库接口、关键词详情、命中路径与重建接口。"""
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="kw_api_")
    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(ROOT / "data" / "demo"),
        "KEYWORD_INDEX": os.path.join(tmp, "keywords.json"),
        "RETRIEVAL": "bm25",
        "QUERY_EXPANSION": "off",
        "KB_APPROVAL": "off",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY"):
        os.environ.pop(key, None)

    from src.server import create_server

    httpd, _pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def get(path):
        req = urllib.request.Request(base + path)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def post(path, payload):
        req = urllib.request.Request(
            base + path, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8")), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8")), dict(exc.headers)

    try:
        status, kb = get("/api/knowledge")
        assert status == 200 and len(kb["files"]) == 1, kb
        assert kb["keywords"]["docs"] == 1, kb["keywords"]
        file = kb["files"][0]
        assert file["keyword_count"] >= 10, file
        assert file["keywords"], file

        status, detail = get("/api/keywords?name=" + urllib.parse.quote(file["name"]))
        assert status == 200 and detail["terms"], detail
        assert any(t["kind"] == "item" for t in detail["terms"]), detail["terms"][:3]

        status, result, headers = post("/api/ask", {"query": "我不吃香菜"})
        assert status == 200, (status, result)
        assert result["path"] == "keyword", result.get("path")
        assert result["api_called"] is False, result
        assert headers.get("X-Answer-Path") == "keyword", headers
        assert "不吃的食物" in result["answer"], result["answer"]

        # 否定作用域：被挡下的「爱吃」不能出现在答案里，且原因要能透传
        status, negated, _ = post("/api/ask", {"query": "我不爱吃香菜"})
        assert status == 200 and negated["path"] == "keyword", negated
        assert "爱吃的食物" not in negated["answer"], negated["answer"]
        assert any(r["reason"] == "negated" for r in negated.get("keyword_rejected") or []), negated

        with urllib.request.urlopen(base + "/metrics", timeout=10) as resp:
            text = resp.read().decode("utf-8")
        assert "rag_keyword_hit_total" in text, text[-800:]
        assert 'rag_keyword_rejected_total{reason="negated"}' in text, text[-800:]

        status, rebuilt, _ = post("/api/keywords/rebuild", {})
        assert status == 200 and rebuilt["ok"], rebuilt
        assert rebuilt["summary"]["docs"] == 1, rebuilt

        status, health = get("/api/health")
        assert health["keywords"]["entries"] >= 10, health["keywords"]
        print("KB files:", len(kb["files"]), "keywords:", kb["keywords"]["terms"],
              "direct:", kb["keywords"]["direct"])
        print("ask path:", result["path"], "api_called:", result["api_called"],
              "terms:", result.get("keyword_terms"))
        print("KEYWORD API TESTS PASSED")
    finally:
        httpd.shutdown()
        httpd.server_close()
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
