"""新增格式入库：PPTX / HTML / EML。

三种格式各测两层：
- 解析器本身（能不能取到对的文字、会不会把噪声收进来）；
- `ingest_bytes` 分派（扩展名 → 解析器 → 落盘 md），这是上传接口真正走的路。
端到端只挑 pptx 一条打 HTTP，确认审批链与「解析成 Markdown 再入库」没断。
"""
import base64
import io
import json
import os
import sys
import tempfile
import threading
import urllib.request
import zipfile
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import eml_text, html_text, ingest, pptx_text  # noqa: E402

FAILED = 0
HOST = "127.0.0.1"


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def make_pptx(slides: list[list[str]]) -> bytes:
    """构造最小 PPTX：每个 list 是一页的若干段落。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml",
                         '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        for index, paragraphs in enumerate(slides, 1):
            body = "".join(
                f'<a:p><a:r><a:t>{text}</a:t></a:r></a:p>' for text in paragraphs)
            archive.writestr(f"ppt/slides/slide{index}.xml",
                             '<?xml version="1.0"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
                             ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                             f'<p:cSld><p:spTree><p:sp><p:txBody>{body}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
    return buffer.getvalue()


def test_pptx() -> None:
    print("PPTX：按页取文字，跳过图片页但保留页码")
    data = make_pptx([
        ["稳盈系列产品介绍", "起购金额 1 元起"],
        [],
        ["费率说明", "管理费率 0.35%", "托管费率 0.05%"],
    ])
    md, meta = pptx_text.extract_pptx(data, "路演材料")
    check("页数正确", meta["slides"] == 3, str(meta))
    check("标题来自文件名", md.startswith("# 路演材料"), md[:30])
    check("三页都有章节标题（空页也留位，否则页码前移）",
          all(f"## 第 {n} 页" in md for n in (1, 2, 3)), md)
    lines = md.splitlines()
    check("段落没有被拼成一行（两条要点各占一行）",
          "稳盈系列产品介绍" in lines and "起购金额 1 元起" in lines, lines[:8])
    check("第三页内容在", "管理费率 0.35%" in md, md[-120:])
    check("空页有明确占位", "无可提取文字" in md, md[:200])
    check("统计里记了空页数", meta["slides_empty"] == 1, str(meta))
    # 页标记是引用里显示「第 N 页」的唯一来源：只写 `## 第 N 页` 标题的话，
    # 切出来的 chunk.page 永远是 null（PPT 明明有页却显示不出来）。
    check("每页都写了页标记（含空页）", md.count("<!--page:") == 3,
          str(md.count("<!--page:")))

    from src import chunking
    chunks = chunking.parse_document(md, "路演.pptx.md")
    check("切出来的块带页码", [c.page for c in chunks] == [1, 2, 3],
          str([c.page for c in chunks]))
    check("页标记没漏进正文", all("<!--page" not in c.text for c in chunks),
          [c.text[:20] for c in chunks])

    try:
        pptx_text.extract_pptx(b"not a zip", "x.pptx")
    except pptx_text.PptxError as exc:
        check("非 ZIP 文件报明确错误", "PPTX" in str(exc), str(exc))
    else:
        check("非 ZIP 文件报明确错误", False)

    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr("docProps/app.xml", "<x/>")
    try:
        pptx_text.extract_pptx(empty.getvalue(), "空.pptx")
    except pptx_text.PptxError as exc:
        check("没有幻灯片的文件报错", "没有幻灯片" in str(exc), str(exc))
    else:
        check("没有幻灯片的文件报错", False)


def test_html() -> None:
    print("HTML：保留标题/列表/表格，丢掉脚本与导航")
    html = """<!doctype html><html><head><title>产品页</title>
    <style>.x{color:red}</style><script>var secret = "不该入库的脚本";</script></head>
    <body><nav>首页 | 产品 | 关于</nav>
    <h1>稳盈系列</h1><p>本产品起购金额为 <b>1 元</b>。</p>
    <h2>费率</h2><ul><li>管理费 0.35%</li><li>托管费 0.05%</li></ul>
    <table><tr><th>期限</th><th>费率</th></tr><tr><td>90天</td><td>0.35%</td></tr></table>
    <footer>版权所有</footer></body></html>"""
    md, meta = html_text.extract_html(html.encode("utf-8"), "产品页")
    check("h1 变成 #", "# 稳盈系列" in md, md[:120])
    check("h2 变成 ##", "## 费率" in md, md[:200])
    check("正文实体与加粗被正确取词", "1 元" in md, md[:200])
    check("列表项被保留", "管理费 0.35%" in md, md[:300])
    check("表格按行拼成 ｜ 分隔", "90天 | 0.35%" in md, md[-160:])
    check("脚本内容没进正文", "不该入库的脚本" not in md, "script 被跳过")
    check("样式表没进正文", "color:red" not in md, "style 被跳过")
    check("导航与页脚被跳过（每页重复的壳不进知识库）",
          "首页 | 产品" not in md and "版权所有" not in md, md[:200])

    gbk = "<html><body><h1>稳盈系列</h1><p>起购金额为 1 元，费率 0.35%。</p></body></html>"
    md2, _ = html_text.extract_html(gbk.encode("gb18030"), "gbk页")
    check("gb18030 编码的页面不乱码", "起购金额为 1 元" in md2, md2[:120])

    try:
        html_text.extract_html(b"<html><body><script>x</script></body></html>", "空")
    except html_text.HtmlError:
        check("没有文字时明确报错（不产出空文档）", True)
    else:
        check("没有文字时明确报错（不产出空文档）", False)


def test_eml() -> None:
    print("EML：主题/正文/编码，附件只计数")
    message = EmailMessage()
    message["Subject"] = "关于稳盈系列费率的确认"
    message["From"] = "client@example.com"
    message["To"] = "sales@example.com"
    message["Date"] = "Mon, 10 Nov 2026 09:00:00 +0800"
    message.set_content("经确认，稳盈系列产品起购金额为 1 元，管理费率按 0.35% 执行。")
    message.add_attachment(b"PDFBINARY", maintype="application", subtype="pdf",
                           filename="附件.pdf")
    md, meta = eml_text.extract_eml(message.as_bytes(), "邮件")
    check("主题进标题", md.startswith("# 关于稳盈系列费率的确认"), md[:60])
    check("发件人与日期被保留（追责要用）",
          "client@example.com" in md and "2026" in md, md[:200])
    check("正文被取出", "起购金额为 1 元" in md, md[:300])
    check("附件数被记录但不是内容", meta["attachments"] == 1 and "PDFBINARY" not in md,
          str(meta))

    # quoted-printable + 非 ASCII，真实邮件最常见的一类
    raw = (
        "Subject: =?utf-8?b?5Lqn5ZOB5Y+j5b6E?=\r\n"
        "From: a@b.com\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "Content-Transfer-Encoding: base64\r\n"
        "MIME-Version: 1.0\r\n\r\n"
        + base64.b64encode("赎回费按持有期限分档。".encode("utf-8")).decode() + "\r\n"
    )
    md2, _ = eml_text.extract_eml(raw.encode("utf-8"), "x")
    check("base64 编码的中文正文能解出来", "赎回费按持有期限分档" in md2, md2[:200])
    check("编码过的标题能解出来", "产品口径" in md2, md2[:80])

    try:
        eml_text.extract_eml(b"Subject: x\r\n\r\n", "空")
    except eml_text.EmlError:
        check("没有正文时明确报错", True)
    else:
        check("没有正文时明确报错", False)


def test_ingest_dispatch() -> None:
    print("ingest_bytes 分派与落盘")
    tmp = Path(tempfile.mkdtemp(prefix="fmt_"))
    cases = [
        ("路演.pptx", make_pptx([["产品介绍", "起购金额 1 元，管理费率 0.35%，托管费率 0.05%。"]]), "pptx"),
        ("产品页.html", (
            "<h1>稳盈系列</h1><p>本产品起购金额为 1 元，管理费 0.35%，托管费 0.05%。</p>"
            "<h2>期限</h2><ul><li>90 天</li><li>180 天</li><li>365 天</li></ul>"
            "<p>赎回费按持有期限分档收取，持有满一年免收赎回费。</p>"
        ).encode("utf-8"), "html"),
        ("确认.eml", None, "eml"),
    ]
    message = EmailMessage()
    message["Subject"] = "费率确认"
    message["From"] = "a@b.com"
    message.set_content("经确认，稳盈系列起购金额为 1 元，管理费率 0.35%，托管费率 0.05%。")
    cases[2] = ("确认.eml", message.as_bytes(), "eml")

    for name, data, fmt in cases:
        result = ingest.ingest_bytes(data, name, tmp)
        check(f"{fmt} 入库成功", result.get("ok") is True, json.dumps(result, ensure_ascii=False)[:160])
        check(f"{fmt} 落盘文件存在",
              bool(result.get("md")) and (tmp / result["md"]).exists(), str(result.get("md")))

    bad = ingest.ingest_bytes(b"x", "readme.xyz", tmp)
    check("未知扩展名报错且列出支持的类型",
          not bad.get("ok") and "PPTX" in bad.get("error", ""), bad.get("error"))


def test_upload_http() -> None:
    print("HTTP：上传 pptx 走审批链")
    tmp = tempfile.mkdtemp(prefix="pptx_up_")
    seed = Path(tmp) / "seed"
    seed.mkdir(parents=True)
    (seed / "占位.md").write_text("# 占位\n\n仅用于初始化知识库。\n", encoding="utf-8")
    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(seed),
        "KEYWORD_INDEX": os.path.join(tmp, "kw.json"),
        "RAW_DIR": os.path.join(tmp, "raw"),
        "RETRIEVAL": "bm25",
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

    data = make_pptx([
        ["稳盈系列产品要素"],
        ["起购金额 1 元起，管理费率 0.35%，托管费率 0.05%。"],
    ])
    body = json.dumps({
        "name": "稳盈路演.pptx",
        "data_b64": base64.b64encode(data).decode(),
    }).encode("utf-8")
    req = urllib.request.Request(base + "/api/knowledge/upload_file", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    check("上传返回 ok", result.get("ok") is True, json.dumps(result, ensure_ascii=False)[:200])
    check("识别为 pptx 格式", result.get("format") == "pptx", str(result.get("format")))
    check("报出了页数", result.get("slides") == 2, str(result.get("slides")))

    # 改后缀的假文件必须 400，而不是 422：这是请求问题，不是文件内容问题
    fake = json.dumps({"name": "伪造.pptx",
                       "data_b64": base64.b64encode(b"not a zip").decode()}).encode("utf-8")
    req = urllib.request.Request(base + "/api/knowledge/upload_file", data=fake,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=30)
        check("假 pptx 被拒", False, "竟然 200")
    except urllib.error.HTTPError as exc:
        detail = json.loads(exc.read().decode("utf-8"))
        message = str(detail.get("message") or detail.get("error") or "")
        check("假 pptx → 400（文件头不匹配）",
              exc.code == 400 and "文件头" in message, f"{exc.code} {detail}")

    httpd.shutdown()
    httpd.server_close()
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def main() -> None:
    import urllib.error  # noqa: F401 —— test_upload_http 用

    test_pptx()
    test_html()
    test_eml()
    test_ingest_dispatch()
    test_upload_http()
    if FAILED:
        print(f"\nDOC FORMATS: {FAILED} FAILED")
        raise SystemExit(1)
    print("\nDOC FORMATS OK")


if __name__ == "__main__":
    import urllib.error  # noqa: F401

    main()
