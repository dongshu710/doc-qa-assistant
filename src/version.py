"""版本号的唯一来源：仓库根目录的 VERSION 文件。

打包脚本、`/api/health`、页面角标都读这里，避免三处各写一个版本号。
"""
from pathlib import Path


def _read_version() -> str:
    try:
        return (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    # 装成包以后项目根不在旁边了，退回包元数据。pyproject 的 dynamic version
    # 也是从同一个 VERSION 读的，两条路径不会漂。
    try:
        from importlib.metadata import version
        return version("agent-notes")
    except Exception:  # noqa: BLE001 —— 取不到版本不该影响启动
        return "0.0.0"


__version__ = _read_version()
