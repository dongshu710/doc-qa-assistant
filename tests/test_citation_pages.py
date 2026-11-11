"""页码级引用：PDF 分页 → Markdown 标记 → chunk.page → 引用 → HTTP。

分四段测，因为这条链每一步都可能悄悄丢信息：
1. PDF 解析要真的按页返回（丢页 = 后面全错）；
2. Markdown 里要有页标记（不写进文件，重建索引时就没了）；
3. 切分要把标记换算成页码并剥掉（漏进正文会被当人话检索）；
4. 引用与原文接口要带出去（前端才显示得出来）。
"""
import json
import os
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import chunking, pdf_ingest  # noqa: E402

FAILED = 0
HOST = "127.0.0.1"


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def make_pdf(pages: list[str]) -> bytes:
    """手写一份多页 PDF：页对象 + 内容流 + xref，够内置解析器读就行。

    不用第三方库生成是刻意的：测试要在零依赖环境里跑，CI 不会装 pypdf。
    """
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objs.append(f"<< /Type /Pages /Count {len(pages)} /Kids [{kids}] >>".encode())
    font_obj = 3 + 2 * len(pages)
    for index, text in enumerate(pages):
        content = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode()
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> "
            f"/Contents {4 + 2 * index} 0 R >>".encode())
        objs.append(b"<< /Length " + str(len(content)).encode()
                    + b" >>\nstream\n" + content + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    count = len(objs) + 1
    out += f"xref\n0 {count}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {count} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def test_pdf_pages() -> bytes:
    print("PDF：按页返回，空页不吞页码")
    # 每页字数要够：入库有质量闸门（每页 <20 字判为扫描件），测试语料太短
    # 会被正确地拒掉，看起来像功能坏了。
    data = make_pdf([
        "alpha page one says the product is for steady customers and has a one yuan minimum",
        "",
        "gamma page three says the redemption fee depends on how long you hold it",
    ])
    pages, meta = pdf_ingest.extract_pages(data)
    check("解析出 3 页", meta.get("pages") == 3, str(meta))
    check("页码从 1 连续", [number for number, _ in pages] == [1, 2, 3],
          str([number for number, _ in pages]))
    check("空页保留为空串（不挤掉后续页码）", pages[1][1] == "", repr(pages[1][1]))
    check("第 3 页内容对得上", "gamma" in pages[2][1], pages[2][1][:40])
    return data


def test_marks(data: bytes) -> None:
    print("Markdown：页标记写进文件")
    tmp = tempfile.mkdtemp(prefix="pagemark_")
    out = Path(tmp)
    result = pdf_ingest.pdf_bytes_to_markdown(
        data, "多页制度.pdf", out, min_chars=1)
    check("入库成功", bool(result.get("ok")), str(result)[:160])
    md = (out / result["md"]).read_text(encoding="utf-8")
    check("文件里有两个页标记（空页不产出标记）", md.count("<!--page:") == 2,
          str(md.count("<!--page:")))
    check("标记里是真实页码 1 与 3",
          "<!--page:1-->" in md and "<!--page:3-->" in md, md[:80])

    stripped = pdf_ingest.strip_page_marks(md)
    check("展示用文本不含标记", "<!--page" not in stripped)
    check("剥掉标记后正文还在", "alpha" in stripped and "gamma" in stripped)


def test_chunk_pages() -> None:
    print("切分：标记换算成页码并剥离")
    # 一节里的两条条款跨页：切分按「第X条」拆开，两块应各自指到自己那页。
    # 若整节只有一块，跨页时只能取起始页——这是有意的，不是漏算。
    raw = (
        "# 制度\n\n## 第一节\n<!--page:1-->\n第1条 甲项正文 alpha。\n"
        "<!--page:2-->\n第2条 乙项正文 beta。\n\n## 第二节\n<!--page:3-->\n"
        "第1条 丙项正文 gamma。\n"
    )
    chunks = chunking.parse_document(raw, "doc.md")
    check("三个块都带页码", all(c.page for c in chunks), str([c.page for c in chunks]))
    check("页码按出现顺序递增", [c.page for c in chunks] == sorted(c.page for c in chunks),
          str([c.page for c in chunks]))
    check("正文不含标记", all("<!--page" not in c.text for c in chunks),
          [c.text[:30] for c in chunks])
    # 同一节里跨页：前半段属于第 1 页，后半段属于第 2 页
    first_two = [c for c in chunks if c.section == "第一节"]
    check("同一节内的跨页块各自取自己那页",
          [c.page for c in first_two] == [1, 2], str([c.page for c in first_two]))

    plain = chunking.parse_document("# 标题\n\n没有页标记的普通文档。\n", "plain.md")
    check("没有标记时 page 是 None（不是 0）", plain[0].page is None, str(plain[0].page))


def test_http() -> None:
    print("HTTP：引用与原文都带页码")
    tmp = tempfile.mkdtemp(prefix="pagecite_")
    seed = Path(tmp) / "seed"
    seed.mkdir(parents=True)
    (seed / "产品说明.md").write_text(
        "# 产品说明\n\n## 概览\n<!--page:1-->\n本产品面向稳健型客户。\n\n"
        "## 要素\n<!--page:7-->\n第1条 稳盈系列产品的起购金额为 1 元。\n",
        encoding="utf-8")
    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(seed),
        "KEYWORD_INDEX": os.path.join(tmp, "kw.json"),
        "RETRIEVAL": "bm25",
        "QUERY_EXPANSION": "off",
        "MIN_SCORE": "0",
        "KB_APPROVAL": "off",
    }
    old = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY", "API_KEYS"):
        os.environ.pop(key, None)

    from src.server import create_server

    httpd, _pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    req = urllib.request.Request(
        base + "/api/ask",
        data=json.dumps({"query": "稳盈系列产品的起购金额是多少"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    citations = result.get("citations") or []
    check("有引用", bool(citations), json.dumps(result, ensure_ascii=False)[:160])
    check("引用带页码且是第 7 页", citations and citations[0].get("page") == 7,
          str(citations[:1]))
    check("答案里没有漏出页标记", "<!--page" not in (result.get("answer") or ""),
          (result.get("answer") or "")[:60])

    if citations:
        doc = citations[0]["doc_id"]
        index = citations[0]["chunk_index"]
        url = base + f"/api/source?doc={urllib.parse.quote(doc)}&chunk={index}"
        with urllib.request.urlopen(url, timeout=20) as resp:
            source = json.loads(resp.read().decode("utf-8"))
        check("/api/source 也返回页码", source.get("page") == 7, str(source)[:120])
        check("原文里没有页标记", "<!--page" not in (source.get("text") or ""),
              (source.get("text") or "")[:60])

    httpd.shutdown()
    httpd.server_close()
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def main() -> None:
    import urllib.parse  # noqa: F401 —— test_http 里用，放这里避免顶层污染

    data = test_pdf_pages()
    test_marks(data)
    test_chunk_pages()
    test_http()
    if FAILED:
        print(f"\nCITATION PAGES: {FAILED} FAILED")
        raise SystemExit(1)
    print("\nCITATION PAGES OK")


if __name__ == "__main__":
    import urllib.parse  # noqa: F401

    main()
