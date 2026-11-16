"""路径与文件名的单一来源：`src/paths.py` + `atomicfile.atomic_write`。

为什么值得单测：
1. 文件名校验从「两份实现、两种失败方式」收敛成一份。收敛本身没有测试兜着，
   下次谁再加一个调用点就会回到「返回 None / 抛异常」混用。
2. 项目根原来散在十几处，少退一层不报错，只是把数据写到 `src/data` 下面。
3. `atomic_write` 是流式写，异常路径必须自己清理临时文件，否则目录里会攒下一堆
   `.tmp-xxxx.part`——而且它们会被附件列表读到（真的会）。
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import paths  # noqa: E402
from src.atomicfile import atomic_write, write_bytes, write_json  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def test_project_root() -> None:
    print("项目根")
    root = paths.PROJECT_ROOT
    check("是仓库根（有 VERSION 与 src/）",
          (root / "VERSION").is_file() and (root / "src" / "paths.py").is_file(),
          str(root))
    check("不是 src/ 本身", root.name != "src", str(root))

    # 全仓不应该再有「自己算项目根」的写法：允许的唯一来源是 src/paths.py
    offenders = []
    for py in (ROOT / "src").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if 'parents[1]' in text and py.name != "paths.py":
            offenders.append(py.relative_to(ROOT).as_posix())
        elif "dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))" in text:
            offenders.append(py.relative_to(ROOT).as_posix())
    check("没有第二处自己算项目根", not offenders, str(offenders))


def test_safe_name() -> None:
    print("文件名校验（唯一一份实现）")
    ok = ["a.md", "文档 1.txt", "2026-11-16.md"]
    for name in ok:
        check(f"接受 {name}", paths.require_safe_name(name) == name)

    bad = [
        "", "   ", None, "..", "../x.md", "a/b.md", "a\\b.md", "/etc/passwd",
        "C:\\Windows\\x.md", "x.exe", "x.md.bak", "a" * 200 + ".md",
        'a<b>.md', "a|b.md", "a\x00b.md", ".hidden.md",
    ]
    for name in bad:
        try:
            got = paths.require_safe_name(name)
        except ValueError:
            check(f"拒绝 {name!r}", True)
        else:
            check(f"拒绝 {name!r}", False, f"竟然返回 {got!r}")

    # URL 里的名字必须先解码再校验：`%2F` 在字符串层面只是个百分号，
    # 直接塞进来会当成合法文件名，解码后就变成路径分隔符。
    from urllib.parse import unquote
    check("解码后的 %2F 被拒", _raises(lambda: paths.require_safe_name(unquote("%2F.md"))))
    check("扩展名白名单可覆盖",
          paths.require_safe_name("x.pdf", (".pdf",)) == "x.pdf")
    check("默认不收 pdf",
          _raises(lambda: paths.require_safe_name("x.pdf")))
    check("长度上限可覆盖",
          paths.require_safe_name("a" * 130 + ".md", None, 200).endswith(".md"))

    # 定义只有一处：别再长出第二个 `_safe_name`
    defs = []
    for py in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in ("_safe_name", "require_safe_name"):
                defs.append(f"{py.relative_to(ROOT).as_posix()}::{node.name}")
    check("全仓只有 paths.require_safe_name 一处定义",
          defs == ["src/paths.py::require_safe_name"], str(defs))


def _raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


def test_atomic_write() -> None:
    print("原子写")
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "sub", "a.txt")
        with atomic_write(target, "w") as handle:
            handle.write("第一行\n第二行\n")
        check("文本写成功", Path(target).read_text(encoding="utf-8") == "第一行\n第二行\n")
        check("换行是 LF", b"\r\n" not in Path(target).read_bytes(),
              repr(Path(target).read_bytes()[:20]))
        check("没有残留临时文件", os.listdir(os.path.dirname(target)) == ["a.txt"],
              str(os.listdir(os.path.dirname(target))))

        # 异常路径：内容不落地，旧内容保留，临时文件清理干净
        try:
            with atomic_write(target, "w") as handle:
                handle.write("写一半")
                raise RuntimeError("模拟中途失败")
        except RuntimeError:
            pass
        check("失败时保留旧内容", Path(target).read_text(encoding="utf-8") == "第一行\n第二行\n")
        check("失败时不留临时文件", os.listdir(os.path.dirname(target)) == ["a.txt"],
              str(os.listdir(os.path.dirname(target))))

        # 并发写同一目标：两个写者都要成功，结果必须是其中一份完整内容
        import threading
        payloads = ["A" * 5000, "B" * 5000]
        errors = []

        def worker(text: str) -> None:
            try:
                with atomic_write(target, "w") as handle:
                    for _ in range(20):
                        handle.write(text)
            except Exception as exc:  # noqa: BLE001 —— 收集起来统一判
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(p,)) for p in payloads]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        body = Path(target).read_text(encoding="utf-8")
        check("并发写不报错", not errors, str(errors))
        check("并发写的结果是某一份完整内容",
              body in ("".join(payloads[0] for _ in range(20)),
                       "".join(payloads[1] for _ in range(20))),
              f"{len(body)} 字符")

        # write_bytes / write_json 仍能用（它们现在都走 atomic_write）
        write_bytes(os.path.join(tmp, "b.bin"), b"\x00\x01")
        check("write_bytes", Path(tmp, "b.bin").read_bytes() == b"\x00\x01")
        write_json(os.path.join(tmp, "c.json"), {"中文": 1})
        check("write_json 不转义中文", "中文" in Path(tmp, "c.json").read_text(encoding="utf-8"))


def main() -> int:
    test_project_root()
    test_safe_name()
    test_atomic_write()
    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("PATHS OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
