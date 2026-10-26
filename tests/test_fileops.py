"""存储区文件读写：越界、后缀、大小、乐观锁。

这些断言对应的是「用户在自己的库上乱点」和「智能体拼错路径」两种真实输入：
一个 `..` 就能读到 SSH 私钥，一次并发写就能把人刚改的内容悄悄覆盖。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import fileops  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"  <- {detail}" if detail else ""))


def expect_error(fn, status: int) -> tuple[bool, str]:
    try:
        fn()
        return False, "没有报错"
    except fileops.FileError as exc:
        return exc.status == status, f"{exc.status}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def test_guard() -> None:
    print("路径守卫")
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "notes").mkdir()
        for bad in ("../secret.md", "notes/../../secret.md", "C:/Windows/win.ini", "/etc/passwd", ""):
            ok, detail = expect_error(lambda b=bad: fileops.read(home, b), 400)
            check(f"拒绝越界/非法路径：{bad or '(空)'}", ok, detail)
        ok, detail = expect_error(lambda: fileops.read(home, "notes/a.exe"), 400)
        check("拒绝非文本后缀", ok, detail)
        ok, detail = expect_error(lambda: fileops.read(home, "notes/none.md"), 404)
        check("文件不存在报 404", ok, detail)


def test_roundtrip() -> None:
    print("读写原文")
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        result = fileops.write(home, "notes/2026/10/a.md", "# 标题\n\n正文\n")
        check("写入返回相对路径", result["path"] == "notes/2026/10/a.md", str(result))
        check("写入返回 rev", len(result["rev"]) == 16, result["rev"])
        got = fileops.read(home, "notes/2026/10/a.md")
        check("读回内容一致", got["content"] == "# 标题\n\n正文\n", got["content"][:40])
        check("读回 rev 与写入一致", got["rev"] == result["rev"])
        check("文件真的是 UTF-8 LF", (home / "notes/2026/10/a.md").read_bytes() == "# 标题\n\n正文\n".encode())

        saved = fileops.write(home, "notes/2026/10/a.md", "# 改过\n", base_rev=got["rev"])
        check("带正确 rev 可以覆盖", fileops.read(home, "notes/2026/10/a.md")["content"] == "# 改过\n",
              str(saved))
        ok, detail = expect_error(
            lambda: fileops.write(home, "notes/2026/10/a.md", "# 又改\n", base_rev=got["rev"]), 409)
        check("rev 过期时拒绝覆盖（不静默丢改动）", ok, detail)
        check("被拒后文件没变", fileops.read(home, "notes/2026/10/a.md")["content"] == "# 改过\n")

        big = "x" * (fileops.MAX_READ_BYTES + 10)
        ok, detail = expect_error(lambda: fileops.write(home, "notes/big.md", big), 413)
        check("超大内容被拒", ok, detail)


def test_open_guard() -> None:
    print("系统编辑器入口")
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        ok, detail = expect_error(lambda: fileops.open_external(home, "notes/none.md"), 404)
        check("打开不存在的文件报 404", ok, detail)
        ok, detail = expect_error(lambda: fileops.open_external(home, "../x.md"), 400)
        check("打开越界路径被拒", ok, detail)


def main() -> int:
    test_guard()
    test_roundtrip()
    test_open_guard()
    print(f"\n{PASS} 项通过，{FAIL} 项失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
