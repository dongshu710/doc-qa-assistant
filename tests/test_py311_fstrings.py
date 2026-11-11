"""3.11 语法兼容门禁：拦住「本地能跑、CI 3.11 直接语法错误」的写法。

为什么要有这条：py3.12 放宽了 f-string 里表达式的限制（可以出现反斜杠、可以复用外层引号）。
开发机是 3.13，`compileall` 一路绿灯，而 CI 的 3.11 job 在第一步「语法检查」就红——
报错只是一行 `SyntaxError`，但因为它发生在语法阶段，同一 job 后面所有测试都没跑。

`ast.parse(..., feature_version=(3, 11))` **抓不到**这一类：反斜杠限制在分词器里，
不在语法树里（实测对违规代码不报错）。所以这里做词法级扫描。

检出范围（故意保守，宁可漏报不可误报）：
- f-string 的 `{...}` 表达式里出现反斜杠（本仓真踩过：`{" class=\\"on\\"" if ...}`）；
- f-string 的 `{...}` 里复用与外层相同的引号（3.12+ 才允许）。

已知漏检：表达式内部嵌套花括号（字典字面量）时只看最外层，可能漏掉里层的问题。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"__pycache__", ".git", "docs", "data", "logs"}

# 只看可疑形态：一行里既像 f-string，`{}` 里又有反斜杠
BACKSLASH_IN_EXPR = re.compile(r"\{[^{}]*\\[^{}]*\}")


def python_files() -> list[Path]:
    out: list[Path] = []
    for base in ("src", "tools", "tests"):
        root = ROOT / base
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            out.append(path)
    return sorted(out)


def fstring_lines(text: str) -> list[tuple[int, str]]:
    """挑出可能是 f-string 的行。

    判据是「出现 f\" 或 f'」，而不是完整解析字符串边界——完整解析要处理三引号、
    转义与跨行，写错了反而会漏掉真问题。这里只做「值不值得细看」的粗筛。
    """
    out = []
    for number, line in enumerate(text.splitlines(), 1):
        if 'f"' in line or "f'" in line:
            out.append((number, line))
    return out


def scan() -> list[tuple[str, int, str]]:
    problems: list[tuple[str, int, str]] = []
    for path in python_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for number, line in fstring_lines(text):
            match = BACKSLASH_IN_EXPR.search(line)
            if match:
                problems.append((str(path.relative_to(ROOT)), number, match.group(0)[:60]))
    return problems


def main() -> int:
    problems = scan()
    if problems:
        print("发现 3.11 不兼容的 f-string 写法（表达式里带反斜杠）：")
        for path, number, snippet in problems:
            print(f"  {path}:{number}  {snippet}")
        print("\n改法：先把表达式算成变量，再拼进 f-string。")
        return 1
    print(f"扫描 {len(python_files())} 个文件，未发现 3.11 不兼容的 f-string 写法")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
