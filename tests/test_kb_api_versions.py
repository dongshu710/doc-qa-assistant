"""服务层集成测试：版本库 + 审批流 + 文档级回滚 + Prometheus 指标。

用法：python tests/test_kb_api_versions.py
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.server import create_server  # noqa: E402


def post(port: int, path: str, payload: dict):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def get(port: int, path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        seed = Path(tmp) / "seed"
        seed.mkdir()
        (seed / "a.md").write_text("# 报销制度\n\n## 一、标准\n\n差旅报销每天 300 元。\n", encoding="utf-8")
        (seed / "b.md").write_text("# 请假制度\n\n## 一、流程\n\n请假需直属主管审批。\n", encoding="utf-8")

        env = {
            "KB_STORE": "on",
            "KB_DIR": str(Path(tmp) / "kb"),
            "KB_SEED_DIR": str(seed),
            "KB_APPROVAL": "on",
            "RETRIEVAL": "vector",
            "EMBEDDING_PROVIDER": "none",
            "LLM_API_KEY": "",
            "DEEPSEEK_API_KEY": "",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY"):
                os.environ.pop(key, None)
            httpd, pipe = create_server("127.0.0.1", 0, knowledge_dir=None)
            port = httpd.server_address[1]
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                health = get(port, "/api/health")
                assert health["kb"]["active"] == "v0001", health["kb"]
                assert health["kb"]["docs"] == 2, health["kb"]
                assert health["retrieval_detail"]["mode"] == "vector"
                print("bootstrap via server OK:", health["kb"])

                # 上传 -> 待审批，不进检索
                status, up = post(port, "/api/knowledge/upload", {
                    "name": "c.md",
                    "content": "# 采购制度\n\n## 一、审批\n\n采购合同由财务负责人签字。\n",
                })
                assert status == 200 and up["pending"] is True, up
                change_id = up["change_id"]
                assert up["version"] == "v0001"
                kb = get(port, "/api/knowledge")
                assert kb["version"] == "v0001" and len(kb["files"]) == 2, kb
                assert kb["pending_changes"] == 1
                print("upload -> pending OK:", change_id)

                # 审批 -> 新版本 + 检索立即包含新文档
                status, approved = post(port, "/api/kb/approve", {"change_id": change_id})
                assert status == 200 and approved["version"] == "v0002", approved
                kb = get(port, "/api/knowledge")
                assert kb["version"] == "v0002" and len(kb["files"]) == 3, kb
                ans = post(port, "/api/ask", {"query": "采购合同由谁签字"})[1]
                assert ans["behavior"] == "answer", ans
                titles = [r["title"] for r in ans["retrieved"]]
                assert any("采购" in t for t in titles), titles
                print("approve -> searchable OK:", ans["behavior"], titles[:2])

                # 覆盖 a.md -> 审批 -> 回滚该文档到 v0001
                _, up2 = post(port, "/api/knowledge/upload", {
                    "name": "a.md", "content": "# 报销制度\n\n## 一、标准\n\n差旅报销每天 900 元。\n"})
                post(port, "/api/kb/approve", {"change_id": up2["change_id"]})
                changed = Path(pipe.knowledge_dir, "a.md").read_text(encoding="utf-8")
                assert "900" in changed

                status, rollback = post(port, "/api/kb/rollback_doc",
                                        {"name": "a.md", "to_version": "v0001"})
                assert status == 200, rollback
                restored = Path(pipe.knowledge_dir, "a.md").read_text(encoding="utf-8")
                assert "300 元" in restored and "900" not in restored, restored
                assert (Path(pipe.knowledge_dir) / "c.md").exists(), "回滚单份文档不能影响其他文档"
                history = get(port, "/api/kb/doc_history?name=a.md")["items"]
                assert len(history) >= 3, history
                print("doc-level rollback OK ->", rollback["version"], "| history", len(history))

                # 拒绝流程
                _, up3 = post(port, "/api/knowledge/upload",
                              {"name": "d.md", "content": "# 测试\n\n内容\n"})
                before = get(port, "/api/health")["kb"]["active"]
                status, rejected = post(port, "/api/kb/reject",
                                        {"change_id": up3["change_id"], "reason": "不需要"})
                assert status == 200 and rejected["status"] == "rejected", rejected
                assert get(port, "/api/health")["kb"]["active"] == before
                print("reject OK")

                # 指标
                metrics = urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/metrics", timeout=10).read().decode("utf-8")
                assert "rag_ask_total" in metrics and "rag_kb_version" in metrics
                assert "rag_ask_duration_seconds_bucket" in metrics
                print("prometheus metrics OK:", len(metrics.splitlines()), "lines")
            finally:
                httpd.shutdown()

    print("ALL KB API VERSION TESTS PASSED")


if __name__ == "__main__":
    main()
