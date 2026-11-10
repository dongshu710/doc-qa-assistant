"""CI 必须真的执行到每一个测试脚本。

为什么单独一条：CI 里漏跑的测试等于不存在——本地绿、线上红，回归拦不住。
这一版之前有 17 个脚本从没进过流水线，其中恰好包括 `test_size`（函数长度门禁）
和 `test_report_render`（汇报页结构），都是改代码时最容易悄悄漂掉的两种。

写法上不解析 YAML：CI runner 只装了 Python，没有 pyyaml，
一条需要第三方库的门禁自己就先跑不起来。改成「只扫 `run:` 的值」——
单行值直接取，`|` / `>` 块标量取更深缩进的行，注释与空行整行丢弃。

为什么不直接拿全文件做字符串匹配（v1.33 修）：
那样把 `python tests/test_size.py` 注释掉、或者写进一句「以后要跑」的说明里，
都算已覆盖，门禁就成了安慰剂。门禁失效的样子和通过一模一样，是最难发现的一类坏法。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILED = 0

# 明确不进 CI 的脚本及原因。留空是常态：能本地跑就该在流水线跑。
EXEMPT: dict[str, str] = {}

_RUN_RE = re.compile(r"^(\s*)run:\s*(.*)$")


def _run_lines(text: str) -> list[str]:
    """抽出 CI 里所有 `run:` 的可执行行。

    只认两种写法：`run: <单行命令>`，以及 `run: |` / `run: >` 之后更深缩进的块。
    注释行一律丢弃——YAML 注释与 run 块里的 shell 注释在这一点上是同一件事：
    写在那里，但不会被执行。
    """
    lines = text.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        match = _RUN_RE.match(lines[index])
        index += 1
        if not match:
            continue
        indent = len(match.group(1))
        value = match.group(2).strip()
        if value and not value.startswith(("|", ">")):
            out.append(value)
            continue
        # 块标量：一直读到缩进回落到 run 所在层或更浅为止
        while index < len(lines):
            current = lines[index]
            if current.strip() and (len(current) - len(current.lstrip())) <= indent:
                break
            index += 1
            command = current.strip()
            if command and not command.startswith("#"):
                out.append(command)
    return out


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def _selftest() -> None:
    """解析器自身的负向自检。

    没有这一段，`_run_lines` 写错（比如漏判注释）会让整份门禁静默失效，
    而它失效的样子和通过完全一样。所以先证明解析器认得「注释不算执行」。
    """
    sample = "\n".join([
        "jobs:",
        "  a:",
        "    steps:",
        "      - name: 单行",
        "        run: python tests/test_real.py",
        "      - name: 被注释掉的一步",
        "        # run: python tests/test_commented.py",
        "        run: |",
        "          # python tests/test_block_comment.py",
        "          python tests/test_block.py",
        "",
    ])
    got = " ".join(_run_lines(sample))
    check("自检：单行 run 被识别", "tests/test_real.py" in got)
    check("自检：块内可执行行被识别",
          "tests/test_block.py" in got and "test_block_comment" not in got)
    check("自检：被注释的 run 不算已覆盖", "test_commented" not in got)


def main() -> int:
    ci_path = ROOT / ".github" / "workflows" / "ci.yml"
    if not ci_path.exists():
        print("  FAIL 找不到 .github/workflows/ci.yml")
        return 1
    ci = ci_path.read_text(encoding="utf-8")

    executable = " ".join(_run_lines(ci))

    print("解析器自检")
    _selftest()

    scripts = sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))
    missing = [n for n in scripts
               if n not in EXEMPT and f"tests/{n}" not in executable]

    print("每个测试脚本都在 CI 里")
    check("测试脚本全部被 CI 引用", not missing,
          "未进 CI: " + ", ".join(missing))
    check("脚本数量不是 0（防止 glob 路径错导致假通过）", len(scripts) > 0,
          str(len(scripts)))
    check("确实解析出了可执行行（防止 run 块扫空后反而全部判 missing）",
          len(executable.strip()) > 0, executable[:80])
    print(f"       共 {len(scripts)} 个脚本，豁免 {len(EXEMPT)} 个，"
          f"可执行行累计 {len(executable.split())} 个词")

    print("豁免项必须写明原因")
    bad = [n for n, why in EXEMPT.items() if not why.strip()]
    check("每个豁免都有理由", not bad, str(bad))

    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("CI COVERAGE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
