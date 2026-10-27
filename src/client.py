"""`python -m src.client` 的入口。

实现放在 `client_cli.py`：入口文件只做转发，避免「用 -m 跑」和「被 import」两种路径
各写一套 argparse。
"""
from .client_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
