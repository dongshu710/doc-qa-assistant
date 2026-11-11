"""Markdown 渲染：语法覆盖 + 转义安全 + 文档站可生成。

为什么自己渲染就要自己测：手写解析器出错的方式很隐蔽——漏一个围栏，后面的整篇
都会被吞进 `<pre>`，页面「看起来正常」但内容全错。这里用具体断言钉住每类语法。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mdrender import render  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def test_blocks() -> None:
    print("块级语法")
    out = render("# 标题\n\n正文一段。\n\n另一段。")
    check("一级标题", "<h1 id=" in out and "标题</h1>" in out, out[:80])
    check("段落各自成 p", out.count("<p>") == 2, str(out.count("<p>")))

    out = render("```python\nprint('<b>')\n```")
    check("围栏代码保留语言类", 'class="lang-python"' in out, out[:80])
    check("代码里的标签被转义", "&lt;b&gt;" in out and "<b>" not in out, out)
    check("代码块不产生段落", "<p>" not in out, out)

    out = render("| A | B |\n|---|---|\n| 1 | 2 |")
    check("表格渲染成 table", "<table>" in out and "<th>A</th>" in out, out[:120])
    check("表格分隔行没被当成数据", out.count("<tr>") == 2, str(out.count("<tr>")))

    out = render("- 一\n- 二\n\n1. 甲\n2. 乙")
    ul_part = out.split("</ul>")[0]
    check("无序列表两项", ul_part.count("<li>") == 2, ul_part)
    check("空行后切成有序列表（不并成一个列表）",
          out.count("<ul>") == 1 and out.count("<ol>") == 1
          and out.count("<li>") == 4, out)

    out = render("> 引用一段")
    check("引用块", "<blockquote>引用一段</blockquote>" in out, out)

    out = render("---")
    check("分隔线", "<hr>" in out, out)


def test_inline() -> None:
    print("行内语法与转义")
    out = render("这是 **粗体** 与 `code` 还有 [链接](https://example.com)。")
    check("粗体", "<strong>粗体</strong>" in out, out)
    check("行内代码", "<code>code</code>" in out, out)
    check("链接", '<a href="https://example.com">链接</a>' in out, out)

    out = render("代码 `a * b` 里的星号不该变斜体")
    check("行内代码里的 * 不当斜体", "<em>" not in out, out)

    out = render("<script>alert(1)</script>")
    check("HTML 被转义（不给注入面）",
          "&lt;script&gt;" in out and "<script>" not in out, out)

    out = render("a & b < c")
    check("& 与 < 都转义", "&amp;" in out and "&lt;" in out, out)


def test_edge() -> None:
    print("边界")
    check("空输入返回空串", render("") == "", repr(render("")))
    out = render("未闭合的围栏\n```\ncode")
    check("未闭合围栏不抛异常", isinstance(out, str), out[:80])
    out = render("# 标题\n\n```\ncode\n```\n\n正文")
    check("围栏后的正文没被吞进代码块", "<p>正文</p>" in out, out)
    long_line = "x" * 5000
    check("超长单行不炸", len(render(long_line)) > 5000)


def test_site() -> None:
    print("文档站生成")
    sys.path.insert(0, str(ROOT / "tools"))
    import build_docs_site  # noqa: E402

    with tempfile.TemporaryDirectory() as tmp:
        count, size = build_docs_site.build(Path(tmp))
        check("生成了页面", count >= 5, str(count))
        check("有内容不为空", size > 10_000, str(size))
        index = Path(tmp) / "index.html"
        check("首页存在（来自 README）", index.exists())
        html = index.read_text(encoding="utf-8")
        check("首页有侧栏导航", 'class="side"' in html and ".html" in html, html[:120])
        check("首页没有未渲染的围栏", "```" not in html, "仍残留 ```")
        check("除首页外还有文档页", len(list(Path(tmp).glob("*.html"))) == count,
              str(len(list(Path(tmp).glob("*.html")))))

    # --check 的判定：生成物过期必须能发现
    with tempfile.TemporaryDirectory() as tmp:
        build_docs_site.build(Path(tmp))
        stale = Path(tmp) / "index.html"
        stale.write_text("旧内容", encoding="utf-8")
        os.environ["_DOCS_SITE_TMP"] = tmp
        code = build_docs_site.main(["--out", tmp, "--check"])
        check("生成物过期时 --check 返回非 0", code == 1, str(code))
    os.environ.pop("_DOCS_SITE_TMP", None)


def main() -> None:
    test_blocks()
    test_inline()
    test_edge()
    test_site()
    if FAILED:
        print(f"\nMDRENDER: {FAILED} FAILED")
        raise SystemExit(1)
    print("\nMDRENDER OK")


if __name__ == "__main__":
    main()
