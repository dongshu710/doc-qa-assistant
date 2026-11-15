"""问答结果的键契约：`src/result.py` 的声明必须覆盖代码里真正写过的键。

为什么需要这条：`AskResult` 是 TypedDict，运行时不校验——多写一个键、少写一个键
都不会报错。声明与实现分叉以后，读代码的人会以为「没有这个字段」，
而它其实一直在产生值（或者反过来，以为有、其实永远是 None）。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.result import AskResult  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def written_keys(path: Path, var: str) -> set[str]:
    """找出对 `var` 的三种写入：`var["k"] = v`、`var.update(k=v)`、`var.setdefault("k", v)`。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        # `result = {"k": v, ...}`：初始字面量里的键也要算写入了，
        # 否则最先建立契约的那 26 个键会被判成「声明了但没人写」。
        value = None
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == var for t in node.targets):
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == var:
            value = node.value
        if isinstance(value, ast.Dict):
            for key in value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    found.add(key.value)
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                and node.value.id == var):
            index = node.slice
            if isinstance(index, ast.Constant) and isinstance(index.value, str):
                found.add(index.value)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("update", "setdefault")
                and isinstance(node.func.value, ast.Name) and node.func.value.id == var):
            for keyword in node.keywords:
                if keyword.arg:
                    found.add(keyword.arg)
            if node.args and isinstance(node.args[0], ast.Dict):
                for key in node.args[0].keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        found.add(key.value)
    return found


def main() -> int:
    declared = set(AskResult.__annotations__)
    sources = {
        "pipeline.py": written_keys(ROOT / "src" / "pipeline.py", "result"),
        "handlers/write.py": written_keys(ROOT / "src" / "handlers" / "write.py", "result"),
    }
    written: set[str] = set()
    for name, keys in sources.items():
        print(f"{name} 写入 {len(keys)} 个键")
        written |= keys

    undeclared = sorted(written - declared)
    check("代码里写过的键都声明了", not undeclared, str(undeclared))

    # 反向不报错：有些键只由外部消费方读取（例如 report），声明了但这里不写。
    unused = sorted(declared - written - {"ts", "usage", "error"})
    check("声明的键没有完全对不上的（允许少量预留）", len(unused) <= 6, str(unused))
    print(f"  声明 {len(declared)} 个，写入 {len(written)} 个")

    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("RESULT CONTRACT OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
