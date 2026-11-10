"""压缩炸弹必须在解压前被拦住。

为什么补这条：上传口只卡「压缩后 6 MB」，而 6 MB 的高压缩比 XML 能解出几百 MB。
`zipfile.read()` 没有配额，几个并发就能把进程吃满——表现是服务被 OOM 杀掉，
日志里什么都没有。

这里测三层：
1. 闸门本身认得出「总量超」与「压缩比异常」；
2. 正常压缩包不被误伤；
3. docx 解析器真的接上了闸门（不是只在单测里通过）。
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import zipguard  # noqa: E402
from src.docx_text import DocxError, extract_docx  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buf.getvalue()


def main() -> int:
    # 1) 总量超限：2 MB 数据，上限设 1 MB
    data = _zip({"a.xml": b"x" * (2 * 1024 * 1024)})
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        try:
            zipguard.guard(archive, max_total=1024 * 1024)
        except zipguard.ZipLimitError as exc:
            check("总量超限被拒", True, str(exc))
        else:
            check("总量超限被拒", False, "没有抛 ZipLimitError")

    # 2) 压缩比异常：2 MB 全 0 压缩后只有几 KB
    bomb = _zip({"zeros.xml": b"\0" * (2 * 1024 * 1024)})
    with zipfile.ZipFile(io.BytesIO(bomb)) as archive:
        try:
            zipguard.guard(archive, max_ratio=50)
        except zipguard.ZipLimitError as exc:
            check("压缩比异常被拒", True, str(exc))
        else:
            check("压缩比异常被拒", False, "没有抛 ZipLimitError")

    # 3) 正常包要能过
    normal = _zip({"word/document.xml": b"<a>" + b"text" * 100 + b"</a>"})
    with zipfile.ZipFile(io.BytesIO(normal)) as archive:
        try:
            size = zipguard.guard(archive)
            check("正常包放行", size > 0, str(size))
        except zipguard.ZipLimitError as exc:
            check("正常包放行", False, str(exc))

    # 4) docx 解析器真的接了闸门：把上限临时调小，喂一个合法 docx 结构
    old_total = zipguard.MAX_TOTAL
    zipguard.MAX_TOTAL = 1024
    try:
        docx = _zip({
            "word/document.xml":
                b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                b"<w:body><w:p><w:r><w:t>" + b"x" * 4096 + b"</w:t></w:r></w:p></w:body></w:document>",
        })
        try:
            extract_docx(docx, "big.docx")
        except DocxError as exc:
            check("docx 解析器先查体积", "上限" in str(exc) or "压缩比" in str(exc), str(exc))
        else:
            check("docx 解析器先查体积", False, "没有拒绝")
    finally:
        zipguard.MAX_TOTAL = old_total

    # 5) 闸门放开后同一个 docx 能正常解析（证明上面失败是因为体积，不是因为文档坏了）
    out = extract_docx(docx, "ok.docx")
    text = out[0] if isinstance(out, tuple) else out
    check("放开上限后正常解析", "xxxx" in str(text), str(text)[:80])

    print()
    if FAILED:
        print(f"{FAILED} 项失败")
        return 1
    print("ZIP GUARD OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
