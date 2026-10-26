"""前端资源：装载、语法、以及「不许再写回 Python 字符串」的护栏。

为什么单独一个测试：
1. `src/web/` 是运行时依赖，文件少了不是少个样式，是整页白屏——必须在启动前就报；
2. JS 语法错只有浏览器知道，一个 script 解析失败会让后面所有脚本不执行；
3. 这次把 20 万字符从 Python 搬到文件，最怕后人图省事又内联回去，所以锁行数。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import theme, web_pages, webassets  # noqa: E402

PASS = 0
FAIL = 0

NEEDED = (
    "base.css", "side.js", "settings.css", "settings.html", "settings.js",
    "files.css", "files.html", "files.js", "files_page.html", "files_page.js",
    "theme_head.html", "theme.js", "util.js",
    "ask.css", "ask.html", "ask.js", "art.txt", "kb.css", "kb.html", "kb.js",
)


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"  <- {detail}" if detail else ""))


def test_files() -> None:
    print("资源文件")
    names = set(webassets.names())
    missing = [n for n in NEEDED if n not in names]
    check("所有资源都在 src/web 下", not missing, f"缺 {missing}")
    check("没有多余的空文件", all(len(webassets.load(n)) > 0 for n in NEEDED),
          "有文件是空的")
    # Windows 上 write_text 会把 \n 翻成 \r\n；资源被改成 CRLF 后仍能跑，
    # 但和 git 里的版本对不上，diff 会整文件变红。这里直接拦住。
    crlf = [n for n in NEEDED if "\r\n" in webassets.load(n)]
    check("换行统一为 LF", not crlf, f"含 CRLF：{crlf}")
    check("装载有缓存", webassets.load("base.css") is webassets.load("base.css"))


def test_pages() -> None:
    print("页面装配")
    check("问答页非空", "<!doctype html>" in web_pages.ASK_HTML and len(web_pages.ASK_HTML) > 100_000,
          f"{len(web_pages.ASK_HTML)} 字符")
    check("知识库页非空", "<!doctype html>" in web_pages.KB_HTML and len(web_pages.KB_HTML) > 100_000,
          f"{len(web_pages.KB_HTML)} 字符")
    check("文件页非空", "<!doctype html>" in theme.FILES_PAGE and len(theme.FILES_PAGE) > 80_000,
          f"{len(theme.FILES_PAGE)} 字符")
    for name, html in (("ask", web_pages.ASK_HTML), ("kb", web_pages.KB_HTML)):
        check(f"{name} 占位符已替换", "__MARK__" not in html and "{{" not in html)
        check(f"{name} 样式内联", "<style>" in html and ".side{" in html)
        check(f"{name} 脚本内联", html.count("<script>") >= 4, f"{html.count('<script>')} 段")
    check("设置里的版本号已填", "{{__version__}}" not in theme.SETTINGS_HTML and "v1." in theme.SETTINGS_HTML)
    # ASCII 图是 SVG，用单引号字符串塞进 JS；成对出现才说明转义没把引号吃掉
    check("空状态插图灌进了脚本", "var ART='" in web_pages.ASK_HTML and "</svg>'" in web_pages.ASK_HTML)


def test_python_thin() -> None:
    """护栏：这两个文件只该剩装配逻辑。再内联回去就等于白搬。"""
    print("Python 侧保持轻薄")
    for name, limit in (("theme.py", 260), ("web_pages.py", 80)):
        path = ROOT / "src" / name
        lines = len(path.read_text(encoding="utf-8").splitlines())
        check(f"{name} 不超过 {limit} 行", lines <= limit, f"实际 {lines} 行")
        # 行数容易糊弄（一行塞一万字符），字节数才是真护栏：曾经是 98 KB
        size = path.stat().st_size
        check(f"{name} 不超过 20 KB", size <= 20_000, f"实际 {size} 字节")


def test_node_check() -> None:
    print("node --check")
    tool = ROOT / "tools" / "check_frontend.py"
    proc = subprocess.run([sys.executable, str(tool)], capture_output=True, text=True,
                          cwd=str(ROOT), timeout=180)
    check("前端自检整体通过", proc.returncode == 0, (proc.stdout or proc.stderr)[-800:])
    check("自检报告了 node 路径", "node:" in proc.stdout, proc.stdout[:200])

    sys.path.insert(0, str(ROOT / "tools"))
    import check_frontend  # noqa: E402
    node = check_frontend.find_node()
    if not node:
        print("  --   本机没有 node，跳过负例")
        return
    check_frontend.NODE = node
    ok, _ = check_frontend.node_check("var a = 1;\n", "good.js")
    check("合法脚本判为通过", ok)
    ok, detail = check_frontend.node_check("var a = {;\n", "bad.js")
    check("语法错误判为失败", not ok and "bad.js" in detail, detail)


def main() -> int:
    test_files()
    test_pages()
    test_python_thin()
    test_node_check()
    print(f"\n{PASS} 通过 / {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
