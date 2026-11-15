"""POST 分派必须覆盖白名单里的每一条路径。

`do_POST` 现在是一层前缀分派 + 四个资源方法。分派写错（少一个前缀、拼错子路径）
的症状很难看：请求落到 `_post_ask` 里，被当成问答解析一遍，最后回一个
「参数不合法」——既不 404 也不报错，排查要翻半天。

这里把白名单（`do_POST` 里那个 `path not in (...)` 的元组）当成唯一事实来源，
逐条验证它能被分派条件命中，并且命中的方法真的存在。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WRITE = ROOT / "src" / "handlers" / "write.py"
READ = ROOT / "src" / "handlers" / "read.py"

FAILED = 0
GROUPS = ("_post_admin", "_post_kb", "_post_data", "_post_ask")


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def declared_paths() -> list[str]:
    """do_POST 里 `path not in (...)` 的白名单。"""
    tree = ast.parse(WRITE.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "do_POST")
    for node in ast.walk(fn):
        if (isinstance(node, ast.Compare) and len(node.ops) == 1
                and isinstance(node.ops[0], ast.NotIn)
                and isinstance(node.comparators[0], ast.Tuple)):
            return [e.value for e in node.comparators[0].elts if isinstance(e, ast.Constant)]
    raise SystemExit("找不到 do_POST 的白名单元组")


def dispatch_conditions(path: Path) -> tuple[set[str], set[str], set[str]]:
    """从 `do_POST` 的 AST 里取出三类别名：相等、`in` 集合、`startswith` 前缀。

    原来这里手抄了一份 `route()` 做「路径 → 分组名」的映射，判据是
    「分组名在 GROUPS 里」，而兜底分支会返回 `_post_ask`——于是任何路径都能通过，
    这条检查等于没写。抄本与源码分叉时更糟：`/api/search/debug` 早已并进
    `_post_data`，抄本还说是 `_post_ask`，红灯永远不会亮。
    改成直接读源码里的分派条件，条件怎么重排都不影响判据。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "do_POST")

    def literals(node) -> list[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return [e.value for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        return []

    eqs: set[str] = set()
    ins: set[str] = set()
    prefixes: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) \
                and node.left.id == "path":
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, ast.Eq):
                    eqs.update(literals(comparator))
                elif isinstance(op, ast.In):
                    ins.update(literals(comparator))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "startswith"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "path"):
            for arg in node.args:
                prefixes.update(literals(arg))
    return eqs, ins, prefixes


def methods(path: Path, prefix: str = "") -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name.startswith(prefix)}


def main() -> int:
    paths = declared_paths()
    print(f"do_POST 白名单 {len(paths)} 条")
    check("白名单不为空", len(paths) >= 15, str(len(paths)))

    print("每条路径都要被分派条件命中")
    eqs, ins, prefixes = dispatch_conditions(WRITE)
    missed = [p for p in paths
              if not (p in eqs or p in ins or any(p.startswith(x) for x in prefixes))]
    check("白名单每条路径都能被 do_POST 的条件命中", not missed,
          f"未命中 {missed}；条件 eq={sorted(eqs)[:6]} prefix={sorted(prefixes)}")

    print("分组方法都真实存在")
    have = methods(WRITE, "_post_")
    for name in GROUPS:
        check(f"{name} 存在", name in have, str(sorted(have)))
    extra = sorted(have - set(GROUPS))
    # 第二层（`_post_kb_upload` 等）由上层方法转交，只要有人 `self.xxx(` 调用就不算孤立；
    # 一个从没被调用的处理方法等于死代码，改到这里的人会以为它还在生效。
    src = WRITE.read_text(encoding="utf-8")
    orphan = [name for name in extra if f"self.{name}(" not in src]
    check("没有从不被调用的处理方法", not orphan, str(orphan))

    print("前缀转交层与按资源分组一致")
    # 走前缀转交的路径不该同时出现在白名单里：前者在 body 解析前就 return 了，
    # 出现在白名单说明它永远走不到自己的处理分支。
    detour = [p for p in paths if p.startswith(("/api/notes", "/api/threads",
                                                "/api/files/", "/api/storage/",
                                                "/api/settings"))]
    check("前缀转交的路径不在白名单里", not detour, str(detour))

    print("GET 侧同样按资源分组")
    got = methods(READ, "_get_")
    check("GET 分组方法齐全", {"_get_pages", "_get_page_html", "_get_meta",
                              "_get_admin", "_get_kb_view", "_get_api_misc"} <= got,
          str(sorted(got)))

    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
