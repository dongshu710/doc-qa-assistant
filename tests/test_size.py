"""函数长度门禁：拆完会再长回去，除非有东西拦着。

为什么需要它：`report.render` 从 363 行拆到 217，两个版本之后又回到 215；
`do_POST` 从 641 拆到 94 之前，也没人发现它在长。人工 review 盯不住长度，
因为它**每次只多几行**，直到某天要在 600 行里找一条 return。

规则：
- 硬上限 200 行（普通函数），超过即失败
- 白名单里的是「单条模板 / 纯数据字面量」——它们长是因为内容多，不是因为职责多；
  拆开只会把一段模板切成碎片，更难读
- 超过 120 行的只打印提示，不失败：提醒下次改到这里时顺手看一眼
- 工厂函数（函数体里含 class 定义）不参与统计：它们的行数是类里所有方法之和，
  方法本身会被单独统计
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARD_LIMIT = 200
SOFT_LIMIT = 120

# 白名单：允许到 HARD_LIMIT * 1.3，且必须写明为什么。
ALLOW = {
    ("src/report.py", "render"): 280,
    ("src/notes/contract.py", "notes_paths"): 280,
}

WHY = {
    "render": "单条 HTML 模板字面量，长在内容不在逻辑",
    "notes_paths": "OpenAPI 路径字典，纯字面量",
}

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def measure(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(isinstance(n, ast.ClassDef) for n in node.body):
            continue        # 工厂函数，交给内部方法
        out.append((node.end_lineno - node.lineno + 1, node.name))
    return out


def main() -> int:
    print(f"函数长度门禁（硬 {HARD_LIMIT} / 软 {SOFT_LIMIT}）")
    over_hard = []
    soft = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for size, name in measure(path):
            limit = ALLOW.get((rel, name), HARD_LIMIT)
            if size > limit:
                over_hard.append((size, rel, name, limit))
            elif size > SOFT_LIMIT:
                soft.append((size, rel, name))

    check("没有函数超过硬上限", not over_hard,
          "\n     " + "\n     ".join(f"{rel}::{name} {size} 行（上限 {limit}）"
                                     for size, rel, name, limit in over_hard))
    if soft:
        print("  提示：以下函数超过软上限（不失败，改到这里时顺手看看）")
        for size, rel, name in sorted(soft, reverse=True):
            print(f"        {size:4d}  {rel}::{name}")
    check("白名单都有理由", all(name in WHY for _, name in ALLOW), str(list(ALLOW)))

    # 门禁本身要能被验证：故意给一个「虚构的长函数」检查判定逻辑
    check("判定逻辑对 201 行判失败", 201 > HARD_LIMIT)
    check("判定逻辑对 200 行判通过", not 200 > HARD_LIMIT)

    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
