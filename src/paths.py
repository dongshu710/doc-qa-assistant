"""项目根与「纯文件名」的单一来源。

两件小事，但都踩过：

1. **项目根**：`Path(__file__).resolve().parents[1]` 在仓库里有十几份，
   有的写成 `dirname(dirname(dirname(abspath(__file__))))`。少退一层不会报错，
   只会让数据目录落到 `src/` 下面或者盘符根——发现时已经在别处生成了半套目录。
2. **文件名过滤**：`_safe_name` 原有两份实现，一份返回 None、一份抛异常。
   混着用的后果是调用方漏判：仓库里真出现过 `Path(safe)` 拿到 None，
   症状是 `TypeError` 变成 500，而不是「文件名不合法」的 400。

所以这里只提供两个东西：`PROJECT_ROOT`，和唯一那个校验函数。
不 import 任何业务模块（它在依赖链最底层，谁都能 import 它）。
"""
from __future__ import annotations

from pathlib import Path

# src/paths.py → parents[0] = src/，parents[1] = 项目根
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 知识库与服务端「文本类」文件的默认扩展名白名单。
# 文档上传（PDF/DOCX/…）另有更宽的集合，由调用方显式传入。
DOC_EXTS = (".md", ".txt")

# Windows 文件系统不允许的字符。`\x00` 单独列出来：它在 Python 字符串里合法，
# 但落盘时抛 ValueError（不是 OSError），会绕过调用方的 except。
_ILLEGAL_CHARS = '<>:"|?*\x00'


def require_safe_name(name, exts=None, maxlen: int = 80) -> str:
    """只接受「纯文件名」，扩展名必须在 `exts` 里；不合法抛 `ValueError`。

    为什么是抛异常而不是返回 None：返回 None 的版本要求每个调用点判一次，
    漏判的代价是 500（见模块注释）。异常只有一个出口，漏处理会直接冒到
    最外层被看见，不会被当成「没传参数」继续往下跑。

    为什么显式拒绝路径分隔符而不是 `basename()` 静默改名：静默改名虽然安全，
    但用户传了 `../x.md` 却看到 `x.md` 被创建，属于隐性行为——他会以为路径生效了。
    """
    raw = str(name or "").strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw:
        raise ValueError(f"非法文件名: {raw!r}")
    # 点开头的名字一律不收：`atomicfile` 的临时文件是 `.tmp-xxxx.part`，
    # 附件目录还会据「以点开头」跳过临时件——真要允许，就得在每处再区分一遍。
    if raw.startswith("."):
        raise ValueError(f"文件名不能以点开头: {raw!r}")
    if len(raw) > maxlen:
        raise ValueError(f"文件名过长（上限 {maxlen} 字符）: {raw!r}")
    allowed = tuple(exts or DOC_EXTS)
    if not raw.lower().endswith(allowed):
        raise ValueError(f"只支持 {' / '.join(allowed)} 文件: {raw!r}")
    if any(ch in raw for ch in _ILLEGAL_CHARS):
        raise ValueError(f"文件名含非法字符: {raw!r}")
    return raw
