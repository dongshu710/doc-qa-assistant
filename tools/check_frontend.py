"""前端资源自检：JS 交 `node --check`，CSS 查括号，页面内联脚本逐个过语法。

为什么需要：前端资源原本是 Python 字符串，写错一个括号只有打开浏览器才知道，
而且一个 `<script>` 解析失败会让它后面的脚本全部不执行——表现是整块界面失灵，
控制台里却只有一行 SyntaxError。搬到 `src/web/` 之后，这些错误可以在提交前拦下。

用法：
    python tools/check_frontend.py            # 全量检查
    python tools/check_frontend.py ask.js     # 只查指定文件

退出码非 0 表示有问题；找不到 node 时只做静态检查并明确提示（不静默跳过）。
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WEB = ROOT / "src" / "web"

PASS = 0
FAIL = 0
NODE = ""


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"\n       {detail.strip()[:600]}" if detail else ""))


def find_node() -> str:
    """优先环境变量，其次 PATH，最后找 WorkBuddy 托管的 node。"""
    for candidate in (os.environ.get("NODE"), shutil.which("node"), shutil.which("node.exe")):
        if candidate and Path(candidate).exists():
            return candidate
    pattern = str(Path.home() / ".workbuddy" / "binaries" / "node" / "versions" / "*" / "node.exe")
    hits = sorted(glob.glob(pattern))
    return hits[-1] if hits else ""


def node_check(source: str, hint: str) -> tuple[bool, str]:
    """把源码写到临时文件里过一遍 `node --check`。

    用临时文件而不是 stdin：`node --check` 对 stdin 的报错没有行号上下文，
    出错时看不出是哪一行。
    """
    suffix = ".mjs" if hint.endswith(".mjs") else ".js"
    with tempfile.NamedTemporaryFile("w", suffix=suffix, encoding="utf-8", delete=False) as handle:
        handle.write(source)
        temp = handle.name
    try:
        proc = subprocess.run([NODE, "--check", temp], capture_output=True, text=True, timeout=30)
        detail = (proc.stderr or "").replace(temp, hint)
        return proc.returncode == 0, detail
    except (OSError, subprocess.SubprocessError) as exc:  # node 在但跑不动
        return False, f"无法执行 node：{exc}"
    finally:
        try:
            os.unlink(temp)
        except OSError:
            pass


def check_js_file(path: Path) -> None:
    ok, detail = node_check(path.read_text(encoding="utf-8"), path.name)
    check(f"js  {path.name}", ok, detail)


def check_css_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    # 注释先剥掉，否则注释里的大括号会干扰计数
    body = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    check(f"css {path.name} 括号配对", body.count("{") == body.count("}"),
          f"{{ 有 {body.count('{')} 个，}} 有 {body.count('}')} 个")
    check(f"css {path.name} 无外部依赖", "@import" not in text and "url(http" not in text,
          "离线可用的前提是不引远程样式")


def page_scripts(html: str) -> list:
    return [m.group(1) for m in re.finditer(r"<script>(.*?)</script>", html, flags=re.S)]


def check_pages() -> None:
    """检查最终拼出来的页面。

    单文件语法对，拼起来不一定对：多个脚本串成一页、模板占位符替换出错，
    这些都只有看最终产物才发现。这里直接拿线上渲染结果再过一遍 node。
    """
    from src import theme, web_pages

    pages = {"ask": web_pages.ASK_HTML, "kb": web_pages.KB_HTML, "files": theme.FILES_PAGE}
    for name, html in pages.items():
        blocks = page_scripts(html)
        check(f"page {name} 有可执行脚本", len(blocks) >= 4, f"实际 {len(blocks)} 段")
        broken = []
        for index, source in enumerate(blocks):
            ok, detail = node_check(source, f"{name}#script{index + 1}")
            if not ok:
                broken.append(f"script{index + 1}: {detail}")
        check(f"page {name} 内联脚本可解析", not broken, "\n".join(broken))
        check(f"page {name} 占位符已替换", "{{" not in html and "__MARK__" not in html,
              "还有没填上的模板占位符")
        # 只允许用户自己去点的那一个取密钥的链接，其余远程地址一律算破线
        allowed = {"https://platform.deepseek.com/api_keys"}
        remote = [u for u in re.findall(r'(?:src|href)="(https?://[^"]+)"', html) if u not in allowed]
        check(f"page {name} 不引外部资源", not remote and "<script src" not in html, str(remote[:3]))


def main(argv: list) -> int:
    global NODE
    NODE = find_node()
    print(f"node: {NODE or '未找到'}")
    wanted = [a for a in argv if not a.startswith("-")]

    files = []
    for pattern in ("*.js", "*.css"):
        for path in sorted(WEB.glob(pattern)):
            if not wanted or path.name in wanted:
                files.append(path)
    total = len([p for p in WEB.iterdir() if p.is_file()]) if WEB.is_dir() else 0
    check("资源文件齐备", total >= 19, f"src/web 下只有 {total} 个文件")

    if not NODE:
        print("  跳过 node --check：本机没有 node，JS 语法未验证（CI 上会跑）")
    for path in files:
        if path.suffix == ".js":
            if NODE:
                check_js_file(path)
            else:
                text = path.read_text(encoding="utf-8")
                check(f"js  {path.name} 非空", len(text) > 40, "文件像是空了")
        else:
            check_css_file(path)

    if not wanted and NODE:
        check_pages()

    print(f"\n{PASS} 通过 / {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
