"""最小可用 Web 服务入口。

  python -m src.server --port 8000

路由与实现已经按职责拆到 `src/handlers/`：
  base.py       HTTP 基类（响应、来源闸门、鉴权、通用动作）
  resources.py  笔记 / 会话 / 文件 / 存储 / 设置
  read.py       页面与只读 API
  write.py      问答 / 知识库 / 设置 / 评测用例
  app.py        组合根（依赖装配 + Handler 拼装）
启动期校验（回环判断、拒启文案）在 `src/startup.py`：它们错了不会报错，
只会静默把库暴露出去，所以值得单独放、单独测。
本文件只保留命令行入口与向后兼容的 `create_server`。
"""
from __future__ import annotations

import argparse
import os
import sys

from . import startup
from .handlers.app import build_app


def create_server(host: str, port: int, knowledge_dir: str | None = None):
    """兼容旧调用点（测试与 tools/ 都从这里起服务）。"""
    return build_app(host, port, knowledge_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description="记忆文档 Web 服务")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--model", help="临时指定模型（等价于设置 LLM_MODEL）")
    args = ap.parse_args()

    if args.model:
        os.environ["LLM_MODEL"] = args.model

    try:
        httpd, pipe = create_server(args.host, args.port)
    except OSError as exc:
        # 端口占用是个人使用最常见的一次性故障，报错误码等于没说
        if startup.bind_conflict(exc):
            print(f"端口 {args.port} 已被占用。可能已经开着一个实例："
                  f"先关掉它，或换个端口 python -m src.server --port {args.port + 1}",
                  file=sys.stderr)
            return 1
        raise

    # 先绑端口、再校验暴露面：让「端口被占用」这种更常见的一次性故障先报出来，
    # 失败时记得把端口还回去。
    try:
        bound_host = str(httpd.server_address[0])
    except (IndexError, TypeError, AttributeError):
        bound_host = args.host
    refusal = startup.exposure_refusal(args.host, bound_host,
                                       getattr(pipe.settings, "api_keys", "") or "")
    if refusal:
        print(refusal, file=sys.stderr)
        httpd.server_close()
        return 1

    print(f"serving http://{args.host}:{args.port}  model={pipe.settings.model} base={pipe.settings.api_base}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        # `shutdown()` 只停循环，不跑 closer：目录监听线程、成本落盘都挂在
        # `server_close()` 上。少了这一步，Ctrl+C 退出时最后一段 token 用量会丢，
        # 而监听线程会跟着进程残留到测试的下一次起服务里。
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
