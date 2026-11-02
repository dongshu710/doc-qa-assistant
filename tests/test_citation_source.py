"""引用可追溯性：每条 citation 的 (doc_id, chunk_index) 必须能解析回同一段原文。

为什么单独一个脚本：1.27.0 上线时这里有个洞——`chunk_index` 是**文档内序号**，
而 `/api/source` 拿它当**全局下标**，除第一篇文档外全部 404。原有 58 个测试都在测
「两个接口各自不报错」，没有一条把它们连起来断言，所以这个 bug 活到了发布。
这个脚本只做一件事：拿真实问答产出的引用去取原文，逐条核对。

运行：python tests/test_citation_source.py
"""
from __future__ import annotations

import json
import os
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

# 覆盖多篇文档的问题：只测一篇的话，全局下标与文档内序号恰好相等，永远测不出问题
QUESTIONS = [
    "理财产品起购金额是多少？",
    "风险测评怎么做？",
    "大额存单起存金额是多少？",
    "双录有什么要求？",
    "投诉多久处理完？",
    "封闭期能提前赎回吗？",
]


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="cite_src_")
    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(ROOT / "data" / "knowledge"),
        "KEYWORD_INDEX": os.path.join(tmp, "keywords.json"),
        "RETRIEVAL": "bm25",
        "QUERY_EXPANSION": "off",
        "KB_APPROVAL": "off",
        "NOTE_HOME": os.path.join(tmp, "home"),
        "SETUP_DONE": "1",
        "APP_CONFIG": os.path.join(tmp, "app.json"),
        "EMBEDDING_PROVIDER": "none",
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

    def post(path, payload):
        req = urllib.request.Request(
            base + path, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def get(path):
        req = urllib.request.Request(base + path)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    failures: list[str] = []
    checked = 0
    docs_hit: set[str] = set()

    for q in QUESTIONS:
        status, data = post("/api/ask", {"query": q})
        assert status == 200, f"提问失败 {q}: {status}"
        cites = data.get("citations") or []
        if not cites:
            print(f"  [skip] {q} 没有引用（{data.get('behavior')}）")
            continue
        for c in cites:
            checked += 1
            doc, idx = c.get("doc_id"), c.get("chunk_index")
            docs_hit.add(doc)
            url = "/api/source?doc=" + urllib.parse.quote(str(doc)) + "&chunk=" + str(idx)
            try:
                st, src = get(url)
            except urllib.error.HTTPError as exc:
                failures.append(f"{q} → doc={doc} chunk={idx} HTTP {exc.code}")
                continue
            if st != 200:
                failures.append(f"{q} → doc={doc} chunk={idx} HTTP {st}")
                continue
            # 三件事必须同时成立：块属于这篇文档、序号自洽、正文非空
            if src.get("doc_id") != doc:
                failures.append(f"{q} → doc={doc} 取回了 {src.get('doc_id')}")
            elif src.get("chunk_index") != idx:
                failures.append(f"{q} → 请求 chunk={idx} 取回 chunk={src.get('chunk_index')}")
            elif not (src.get("text") or "").strip():
                failures.append(f"{q} → doc={doc} chunk={idx} 正文为空")
            elif c.get("section") and src.get("section") != c.get("section"):
                failures.append(
                    f"{q} → 章节不一致：引用 {c.get('section')!r} vs 原文 {src.get('section')!r}")

    # 只覆盖一篇文档时下标必然对齐，测不出错位；这条断言防止"改窄了测试"
    if len(docs_hit) < 2:
        failures.append(f"只覆盖到 {len(docs_hit)} 篇文档，无法证明跨文档定位正确")

    print(f"核对引用 {checked} 条，覆盖文档 {len(docs_hit)} 篇")
    if checked == 0:
        failures.append("一条引用都没产生，用例失效")

    if failures:
        print("\n引用无法回到原文：")
        for f in failures:
            print("  ✗", f)
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        raise SystemExit(1)
    print("✓ 每条引用都能定位回原文")


if __name__ == "__main__":
    main()
