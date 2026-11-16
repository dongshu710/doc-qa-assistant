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
- **类体行数单独一条线**（v1.43.0 起）：路由类从工厂闭包里搬成模块级类之后，
  「这个类有多大」变成可量化的东西，必须看得见。类不按函数上限判——它本来就是
  几十个方法的容器；这里只拦「一个文件里长出一个 2000 行的上帝类」。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARD_LIMIT = 200
SOFT_LIMIT = 120
# 类体上限：路由类的真实规模在 500–1200 行之间（方法多，不是方法长）。
# 1300 是当前最大类（WriteRoutes）再留一点余量——它继续长就该拆成两个类了。
CLASS_HARD = 1300
CLASS_SOFT = 600
# 类体行数要能被看见：这两个类的位置是「结构层」的锚点，涨了要有人知道。
CLASS_SHOW = 3

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


def measure_classes(path: Path) -> list[tuple[int, str]]:
    """类体行数。嵌套类一并统计——它长起来同样是上帝类。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [(node.end_lineno - node.lineno + 1, node.name)
            for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]


def main() -> int:
    top = max(ALLOW.values(), default=HARD_LIMIT)
    # 把白名单的实际上限写进输出：原来只印「硬 200」，看输出的人会以为
    # 两个 280 行的函数已经违规了，实际它们被白名单放着——这种错觉会让人
    # 对门禁的严格程度判断错。
    print(f"函数长度门禁（普通函数硬 {HARD_LIMIT} / 软 {SOFT_LIMIT}；"
          f"白名单 {len(ALLOW)} 项，最高放到 {top}）")
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

    # 类体行数：先报数再判定。「这个类有多大」本身就是要被看见的信息，
    # 只判不报的话，下次有人把它撑到 1290 行也没人知道逼近上限了。
    classes: list[tuple[int, str, str]] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        classes.extend((size, rel, name) for size, name in measure_classes(path))
    classes.sort(reverse=True)
    print(f"  最大的 {CLASS_SHOW} 个类（类体行数；软 {CLASS_SOFT} / 硬 {CLASS_HARD}）")
    for size, rel, name in classes[:CLASS_SHOW]:
        print(f"        {size:4d}  {rel}::{name}")
    over_class = [c for c in classes if c[0] > CLASS_HARD]
    check("没有类超过类体上限", not over_class,
          "\n     " + "\n     ".join(f"{rel}::{name} {size} 行（上限 {CLASS_HARD}）"
                                     for size, rel, name in over_class))

    # 门禁本身要能被验证，而且不能只做算术：`201 > 200` 只是解释器在算数，
    # 完全没经过 measure()。真出问题的是「量长度的那条路」，所以让它真跑一遍。
    check("判定逻辑对 201 行判失败", 201 > HARD_LIMIT)
    check("判定逻辑对 200 行判通过", not 200 > HARD_LIMIT)

    import tempfile
    body = "".join(f"    v{i} = {i}\n" for i in range(199))
    fake = f"def fake_long():\n{body}    return 1\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(fake)
        fake_path = Path(fh.name)
    try:
        measured = measure(fake_path)
    finally:
        fake_path.unlink(missing_ok=True)
    check("自检：measure 真的量出 201 行",
          bool(measured) and measured[0] == (201, "fake_long"), str(measured))

    # 类体那条线同样要能自证：造一个 61 行的类，量出来必须对得上。
    fake_cls = "class Fake:\n" + "".join(f"    v{i} = {i}\n" for i in range(60)) + "\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(fake_cls)
        fake_cls_path = Path(fh.name)
    try:
        measured_cls = measure_classes(fake_cls_path)
    finally:
        fake_cls_path.unlink(missing_ok=True)
    check("自检：measure_classes 真的量出类体行数",
          measured_cls == [(61, "Fake")], str(measured_cls))

    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
