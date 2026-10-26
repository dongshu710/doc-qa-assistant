"""前端资源读取：真正的 .css / .js / .html 放在 `src/web/` 下。

为什么不再用 Python 字符串：20 万字符的三引号字符串没有语法高亮、没法 `node --check`、
改动只能靠肉眼对齐缩进，一次缩进错位就是白屏。搬到文件后编辑器能标红，CI 能校验。

运行时不变：启动时一次性读进内存并缓存，仍然内联拼进 HTML，不新增静态资源路由，
不引入构建步骤，断网可用。改完资源要重启进程才生效——和改 Python 一样。
"""
from __future__ import annotations

import os
from functools import lru_cache

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


@lru_cache(maxsize=None)
def load(name: str) -> str:
    """按原样读一个资源文件。

    newline="" 关闭换行翻译：文件里的 \\n 就是字符串里的 \\n，
    否则 Windows 上的 \\r\\n 会被悄悄改写，和迁移前的字节对不上。
    """
    path = os.path.join(WEB_DIR, name)
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def path_of(name: str) -> str:
    return os.path.join(WEB_DIR, name)


def names() -> list:
    """资源清单（测试与打包脚本共用，避免各写一份列表）。"""
    try:
        return sorted(n for n in os.listdir(WEB_DIR) if os.path.isfile(os.path.join(WEB_DIR, n)))
    except OSError:
        return []
