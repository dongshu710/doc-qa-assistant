"""Web 服务冒烟测试：起一个临时端口，验证 /api/health 与 /api/ask。

用法：python tests/test_server.py
（未配置 LLM_API_KEY 时自动走离线抽取，配置后为真实模型。）
"""
import json
import sys
import threading
import urllib.parse
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.server import create_server  # noqa: E402

httpd, pipe = create_server("127.0.0.1", 0, str(ROOT / "data" / "knowledge"))
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()

try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=10) as resp:
        health = json.loads(resp.read().decode("utf-8"))
    print("health:", health)
    assert health.get("retrieval") == "vector"
    assert health.get("guards", {}).get("budget", {}).get("limit", 0) > 0

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/examples?n=4", timeout=10) as resp:
        examples = json.loads(resp.read().decode("utf-8"))["items"]
    assert len(examples) >= 1
    print("examples:", examples)

    pages = {}
    for page, needle in (("/ask", "今天想记住什么"), ("/kb", "拖拽或点击上传"),
                         ("/files", "pf-grid")):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{page}", timeout=10) as resp:
            pages[page] = resp.read().decode("utf-8")
        assert needle in pages[page], page
        assert 'href="/insights"' not in pages[page], "导航里不该再出现已下线的页面"
    # /files 是「加不进客户端工具栏」时的固定地址，必须自己也能开出来
    assert "<title>文件 ·" in pages["/files"], "文件页标题没带上品牌名"
    assert 'id="setPanel"' in pages["/files"], "文件页也要有设置抽屉骨架"
    assert 'id="filesDot"' in pages["/files"], "文件页导航上要有红点按钮"
    print("pages OK（问答 / 知识库 / 文件）")

    # 笔记入口：问答页能发起保存，知识库页有两个分区且不是嵌套关系。
    # 结构错位（面板套进另一个面板）在浏览器里表现为「点了没反应」，字符串断言抓不到，
    # 所以这里用 HTMLParser 真的看一次父子关系。
    assert 'id="noteDialog"' in pages["/ask"] and "存为笔记" in pages["/ask"]
    assert 'id="panelNotes"' in pages["/kb"] and 'data-tab="notes"' in pages["/kb"]

    class PanelFinder(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack: list[str] = []
            self.parents: dict[str, list[str]] = {}
            self.ids: set[str] = set()

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            node_id = attrs.get("id")
            if node_id:
                self.parents[node_id] = list(self.stack)
                self.ids.add(node_id)
            if tag not in ("br", "img", "input", "meta", "link", "hr", "source", "path",
                           "circle", "rect", "use", "stop"):
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass

    finder = PanelFinder()
    finder.feed(pages["/kb"])
    assert "panelDocs" in finder.ids and "panelNotes" in finder.ids, finder.ids
    assert "panelNotes" not in " ".join(finder.parents.get("panelNotes", [])), "笔记面板被套进了文档面板"
    assert finder.parents.get("panelDocs")[-1:] == ["main"], finder.parents.get("panelDocs")
    print("notes panels OK（两个分区同级，未嵌套）")

    # 旧入口保留 302，收藏夹里的链接不能断
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    for page, want in (("/", "/ask"), ("/index.html", "/ask"), ("/insights", "/ask"),
                       ("/dashboard", "/ask"), ("/report", "/ask")):
        try:
            opener.open(f"http://127.0.0.1:{port}{page}", timeout=10)
            raise AssertionError(f"{page} 未重定向")
        except urllib.error.HTTPError as exc:
            assert exc.code == 302, (page, exc.code)
            assert exc.headers.get("Location") == want, (page, exc.headers.get("Location"))
    print("legacy redirect OK")

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/l3", timeout=10) as resp:
        l3 = json.loads(resp.read().decode("utf-8"))
    print("l3 available:", l3.get("available"), "| avg:", (l3.get("avg") or {}).get("faithfulness"))

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/ask",
        data=json.dumps({"query": "稳盈系列的起购金额是多少"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Idempotency-Key": "smoke-ask"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    print("ask:", {k: data.get(k) for k in ("channel", "model", "behavior", "mode", "degraded", "latency_ms")})
    print("answer:", data["answer"])

    # 引用必须能回原文：doc_id/chunk_index 齐全，/api/source 能取到同一块
    cite = data["citations"][0]
    assert cite.get("doc_id") and cite.get("chunk_index") is not None, cite
    assert "kb_version" in data, "响应应带版本字段（未启用版本库时为 None）"
    src_url = (f"http://127.0.0.1:{port}/api/source?doc="
               + urllib.parse.quote(str(cite["doc_id"]))
               + f"&chunk={cite['chunk_index']}")
    with urllib.request.urlopen(src_url, timeout=10) as resp:
        src = json.loads(resp.read().decode("utf-8"))
    assert src["doc_id"] == cite["doc_id"] and src["text"].strip(), src
    assert src.get("version") == data.get("kb_version"), src
    print("source:", src["title"], "·", src["section"], "|", len(src["text"]), "chars")
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/source?doc=x&chunk=99999", timeout=10)
        raise AssertionError("越界 chunk 应 404")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404

    with urllib.request.urlopen(req, timeout=90) as resp:
        replay = json.loads(resp.read().decode("utf-8"))
        replay_header = resp.headers.get("X-Idempotent-Replay")
    assert replay["trace_id"] == data["trace_id"] and replay_header == "true"
    print("idempotency: replay OK")

    miss_req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/ask",
        data=json.dumps({"query": "今天天气怎么样"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(miss_req, timeout=30) as resp:
        miss = json.loads(resp.read().decode("utf-8"))
    assert miss["behavior"] == "no_answer"
    assert miss["answer"] == "无法找到答案。"
    assert miss.get("similar_questions")
    # 未命中也要给出可解释的元信息：最高分与阈值，让人知道差多远
    assert miss["min_score"] > 0 and miss["gate_score"] < miss["min_score"], miss
    print("no-answer:", miss["answer"], "| gate=", round(miss["gate_score"], 3),
          "< min=", miss["min_score"], "| similar:", len(miss["similar_questions"]))

    # 未命中的反馈要能收「期望答案 + 缺失文档」
    miss_fb = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/feedback",
        data=json.dumps({"trace_id": miss["trace_id"], "useful": False,
                         "behavior": miss["behavior"], "query": "今天天气怎么样",
                         "expected": "应说明这是域外问题", "document": "产品说明.md",
                         "kb_version": miss.get("kb_version")}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(miss_fb, timeout=10) as resp:
        miss_fb_res = json.loads(resp.read().decode("utf-8"))
    assert miss_fb_res.get("ok") is True and miss_fb_res.get("need") is True, miss_fb_res
    print("no-answer feedback OK:", miss_fb_res)

    page = urllib.request.urlopen(f"http://127.0.0.1:{port}/ask", timeout=10).read().decode("utf-8")
    for token in ("导出 Markdown", "没找到需要的答案", "知识库 '"):
        assert token in page, token

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/admin/config", timeout=10) as resp:
        admin = json.loads(resp.read().decode("utf-8"))
    assert admin.get("ok") is True and "runtime" in admin
    print("admin config:", admin["runtime"])

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/metrics", timeout=10) as resp:
        metrics = json.loads(resp.read().decode("utf-8"))
    print("metrics.requests:", metrics.get("requests"))

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/knowledge", timeout=10) as resp:
        kb = json.loads(resp.read().decode("utf-8"))
    print("knowledge:", kb["total_chunks"], "chunks /", len(kb["files"]), "files")

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/trace?limit=5", timeout=10) as resp:
        trace = json.loads(resp.read().decode("utf-8"))
    print("trace items:", len(trace["items"]))

    reload_req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/reload",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(reload_req, timeout=10) as resp:
        rl = json.loads(resp.read().decode("utf-8"))
    print("reload:", rl)
    assert rl.get("ok") is True

    fb_req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/feedback",
        data=json.dumps({"trace_id": data.get("trace_id"), "useful": False, "comment": "smoke test"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(fb_req, timeout=10) as resp:
        fb = json.loads(resp.read().decode("utf-8"))
    print("feedback:", fb)

    assert health["status"] == "ok"
    assert health["channel"], "health 应返回端点标识"
    assert data["behavior"] == "answer" and data["answer"]
    assert fb.get("ok") is True
    print("SMOKE OK")
finally:
    httpd.shutdown()
