"""知识库上传/删除冒烟：目录穿越、扩展名、大小、重建索引。

用法：python tests/test_kb_api.py
"""
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("LLM_CHANNEL", "glm")

from src.server import create_server  # noqa: E402

httpd, pipe = create_server("127.0.0.1", 0, str(ROOT / "data" / "knowledge"))
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"


def post(path: str, payload: dict):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def get(path: str):
    with urllib.request.urlopen(base + path, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


try:
    before = get("/api/knowledge")
    name = "_smoke_upload.md"
    content = "# 冒烟测试文档\n\n## 一、测试条款\n\n本文件仅用于接口冒烟：某产品起购金额为 88 元。\n"

    status, data = post("/api/knowledge/upload", {"name": name, "content": content})
    print("upload:", status, data)
    assert status == 200 and data["ok"], data

    after = get("/api/knowledge")
    assert len(after["files"]) == len(before["files"]) + 1
    assert after["total_chunks"] > before["total_chunks"]
    print("index rebuilt:", before["total_chunks"], "->", after["total_chunks"], "chunks")

    # 目录穿越 / 非法扩展名
    for bad in ("../evil.md", "/etc/passwd.txt", "x.exe"):
        status, data = post("/api/knowledge/upload", {"name": bad, "content": "x"})
        assert status == 400, (bad, status, data)
    print("traversal/extension guard OK")

    status, data = post("/api/knowledge/delete", {"name": name})
    print("delete:", status, data)
    assert status == 200 and data["ok"]

    final = get("/api/knowledge")
    assert len(final["files"]) == len(before["files"])
    assert not os.path.exists(Path(pipe.knowledge_dir) / name)
    print("KB API SMOKE OK")
finally:
    httpd.shutdown()
