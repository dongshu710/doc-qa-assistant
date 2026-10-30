"""前端资源读取：真正的 .css / .js / .html 放在 `src/web/` 下。

为什么不再用 Python 字符串：20 万字符的三引号字符串没有语法高亮、没法 `node --check`、
改动只能靠肉眼对齐缩进，一次缩进错位就是白屏。搬到文件后编辑器能标红，CI 能校验。

运行时不变：启动时一次性读进内存并缓存，仍然内联拼进 HTML，不新增静态资源路由，
不引入构建步骤，断网可用。改完资源要重启进程才生效——和改 Python 一样。

为什么用 `importlib.resources` 而不是 `os.path.join(__file__, ...)`：
装成 wheel 或打成单文件 `.pyz` 之后，资源在压缩包里，`open()` 拿不到。
`importlib.resources` 对「真实目录」和「zip 内条目」是同一套接口，
源码运行、pip 安装、单文件分发三种形态都能读。
"""
from __future__ import annotations

from functools import lru_cache
from importlib.resources import files as _files


def _web_dir():
    """返回 `src/web` 的资源句柄（能读，但不一定是真实路径）。"""
    return _files(__package__) / "web"


@lru_cache(maxsize=None)
def load(name: str) -> str:
    """按原样读一个资源文件。

    用 `read_bytes().decode()` 而不是 `read_text()`：后者会做换行翻译
    （CRLF → LF），和迁移前的 `newline=""` 语义不一致——Windows 上
    autocrlf 检出后同一份文件读出的字节会变。字节直读不翻译。
    """
    return (_web_dir() / name).read_bytes().decode("utf-8")


def path_of(name: str) -> str:
    """真实文件系统路径；资源不在磁盘上时（如 .pyz 内）返回空串。"""
    try:
        handle = _web_dir() / name
        return str(handle) if handle.is_file() and _is_fs(handle) else ""
    except (OSError, TypeError, AttributeError, ValueError):
        return ""


def _is_fs(handle) -> bool:
    """zip 里的 Traversable 也实现了 `is_file()`，但它没有真实路径。"""
    return hasattr(handle, "__fspath__")


def names() -> list:
    """资源清单（测试与打包脚本共用，避免各写一份列表）。"""
    try:
        return sorted(item.name for item in _web_dir().iterdir() if item.is_file())
    except (OSError, TypeError):
        return []
