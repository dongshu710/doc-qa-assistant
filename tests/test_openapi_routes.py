"""OpenAPI 与真实 dispatch 的双向对齐。

为什么需要这条：`/api/cases/run`、`/api/audit`、`/api/settings/*` 这些端点
曾经只活在 `if/elif` 里，契约上一个字都没有。后果不是「文档不好看」——
`routing.allowed_methods()` 从契约里取方法表，用来把「方法用错」判成 405，
于是契约缺一条，那条路由的方法判定就一起错（真发生过：`/api/storage/restore`
对 GET 回 404 而不是 405，而早已删掉的 `/api/storage/usage` 还留在表里）。

这里静态扫 dispatch 源码里的路径字面量，与 `build_spec()` 双向比对：
- 扫到的路径必须写进契约（否则新增端点又漏登记）；
- 契约里的路径必须有实现（否则文档在骗人）。
两边都不起服务，纯静态，所以能在 CI 里当硬门禁。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILED = 0

# 只认这几类开头：页面的 HTML 路由不在 OpenAPI 里，不算泄漏。
# `/dify/` 是给 Dify 用的适配面，也要进这张表——它的消费者在外部，
# 漏登记不会有本项目的页面报错，只会让对方的请求静默失败。
WANTED = ("/api/", "/dify/", "/mcp", "/tools.json", "/openapi.json", "/metrics")

# `/api/notes/{id}/assets/{name}` 这类模板里的参数段；判断「有实现」时要跳过。
_PARAM = re.compile(r"^\{[a-z_]+\}$")


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def _sources() -> list[Path]:
    """dispatch 所在的全部源码：handlers 四件套 + 笔记的独立 dispatch。

    `src/notes/api.py` 自带一套 if/elif（笔记服务能脱离主服务单独跑），
    `/api/notes/rebuild`、`/api/notes/stats` 就只在那里出现。
    """
    files = sorted((ROOT / "src" / "handlers").glob("*.py"))
    notes_api = ROOT / "src" / "notes" / "api.py"
    if notes_api.exists():
        files.append(notes_api)
    return files


def scan_literals() -> set[str]:
    """扫 dispatch 里的路径字面量。

    跳过以 `/` 结尾的（`/api/kb/` 这种是前缀判断，不是端点本身）——
    子端点会以完整字面量出现在别处。
    """
    found: set[str] = set()
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for raw in re.findall(r'"(/[^"\n]{1,60})"', text):
            if not raw.startswith(WANTED) or raw.endswith("/"):
                continue
            found.add(raw)
    return found


def spec_routes() -> dict[str, set[str]]:
    from src.openapi import build_spec

    spec = build_spec("0.0.0", {"mode": "open"}, "m", "bm25")
    out: dict[str, set[str]] = {}
    for path, ops in spec["paths"].items():
        methods = {m.upper() for m in ops
                   if m.lower() in ("get", "post", "put", "patch", "delete")}
        if methods:
            out[path] = methods
    return out


def handler_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _sources())


def has_impl(path: str, literals: set[str], source: str) -> bool:
    """契约里的路径是否真有实现。

    两种形态：完整字面量（大多数），或「资源前缀 + action 末段」拼接
    （`_files` / `_storage` / `_settings` 里用 `path.rsplit("/", 1)[-1]` 分派）。
    后者的证明是：末段作为带引号的字面量出现在源码里，且资源前缀存在。
    """
    if path in literals:
        return True
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        return False
    if any(_PARAM.match(p) for p in parts):
        # 模板路径：要求它的静态前缀（形如 /api/notes/）在 dispatch 里出现过
        cut = next(i for i, p in enumerate(parts) if _PARAM.match(p))
        prefix = "/" + "/".join(parts[:cut]) + "/"
        return prefix in source
    last = parts[-1]
    parent = "/" + "/".join(parts[:-1])
    return f'"{last}"' in source and parent in source


def test_literals_are_declared() -> None:
    print("dispatch 里的每条路径都写进了契约")
    spec = spec_routes()
    literals = scan_literals()

    def declared(path: str) -> bool:
        if path in spec:
            return True
        # 契约里的模板也算：/api/notes/xxx 命中 /api/notes/{id}
        for template in spec:
            if "{" not in template:
                continue
            left, right = template.strip("/").split("/"), path.strip("/").split("/")
            if len(left) == len(right) and all(
                    a.startswith("{") or a == b for a, b in zip(left, right)):
                return True
        return False

    missing = sorted(p for p in literals if not declared(p))
    check("无漏登记", not missing, "未进 OpenAPI: " + ", ".join(missing))
    print(f"       扫描到 {len(literals)} 条路径字面量，契约 {len(spec)} 条")


def test_spec_has_impl() -> None:
    print("契约里的每条路径都有实现")
    spec = spec_routes()
    literals = scan_literals()
    source = handler_source()
    ghosts = sorted(p for p in spec if not has_impl(p, literals, source))
    check("无幽灵端点", not ghosts, "契约有、代码无: " + ", ".join(ghosts))


def test_methods_table_single_source() -> None:
    """方法表只从契约来：补丁表删掉后，幽灵路由自然消失。"""
    print("方法表与契约一致")
    from src import routing

    check("已无 _EXTRA_METHODS 补丁表", not hasattr(routing, "_EXTRA_METHODS"))
    check("拼接路由认得方法（restore）",
          routing.allowed_methods("/api/storage/restore") == {"POST"},
          str(routing.allowed_methods("/api/storage/restore")))
    check("已删端点不再认得（usage）",
          routing.allowed_methods("/api/storage/usage") is None,
          str(routing.allowed_methods("/api/storage/usage")))
    check("模板路由认得方法",
          routing.allowed_methods("/api/threads/t_123") == {"GET", "PUT", "DELETE"},
          str(routing.allowed_methods("/api/threads/t_123")))
    check("未知路径返回 None", routing.allowed_methods("/api/nope") is None)


def test_internal_marks() -> None:
    """页面专用端点标 x-internal；对外端点不标。"""
    print("内部端点标记")
    from src.openapi import build_spec

    spec = build_spec("0.0.0", {"mode": "open"}, "m", "bm25")
    for path in ("/api/settings", "/api/files/raw", "/api/threads/{id}", "/mcp"):
        ops = spec["paths"].get(path) or {}
        marked = [m for m, op in ops.items() if op.get("x-internal")]
        check(f"{path} 标了 x-internal", len(marked) == len(ops), str(list(ops)))
    for path in ("/api/ask", "/api/knowledge"):
        ops = spec["paths"][path]
        check(f"{path} 没标 x-internal",
              all(not op.get("x-internal") for op in ops.values()))


def main() -> int:
    test_literals_are_declared()
    test_spec_has_impl()
    test_methods_table_single_source()
    test_internal_marks()
    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("OPENAPI ROUTES OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
