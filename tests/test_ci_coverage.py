"""CI 必须跑到每一个测试脚本。

为什么单独一条：CI 里漏跑的测试等于不存在——本地绿、线上红，回归拦不住。
这一版之前有 17 个脚本从没进过流水线，其中恰好包括 `test_size`（函数长度门禁）
和 `test_report_render`（汇报页结构），都是改代码时最容易悄悄漂掉的两种。

写法上不解析 YAML：CI runner 只装了 Python，没有 pyyaml，
一条需要第三方库的门禁自己就先跑不起来。直接按文件名做字符串匹配，
糙但对——`tests/test_server.py` 与 `tests/test_server_redis.py` 靠全名区分。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILED = 0

# 明确不进 CI 的脚本及原因。留空是常态：能本地跑就该在流水线跑。
EXEMPT: dict[str, str] = {}


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def main() -> int:
    ci_path = ROOT / ".github" / "workflows" / "ci.yml"
    if not ci_path.exists():
        print("  FAIL 找不到 .github/workflows/ci.yml")
        return 1
    ci = ci_path.read_text(encoding="utf-8")

    scripts = sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))
    missing = [n for n in scripts
               if n not in EXEMPT and f"tests/{n}" not in ci]

    print("每个测试脚本都在 CI 里")
    check("测试脚本全部被 CI 引用", not missing,
          "未进 CI: " + ", ".join(missing))
    check("脚本数量不是 0（防止 glob 路径错导致假通过）", len(scripts) > 0,
          str(len(scripts)))
    print(f"       共 {len(scripts)} 个脚本，豁免 {len(EXEMPT)} 个")

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
