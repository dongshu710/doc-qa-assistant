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

**启动顺序**在这里，不在 `build_app` 里。顺序是刻意的：
bind → 立刻起一个「正在启动」应答器 → 建索引（慢）→ 交棒给真处理器。
反过来（先建索引再 bind）在 5 万块语料上意味着几分钟的 `ECONNREFUSED`——
客户端看到的是「服务没起来」，而它正在正常加载。
"""
from __future__ import annotations

import argparse
import os
import sys
import threading

from . import startup
from .config import load_settings
from .handlers.app import build_app
from .http_server import BoundedHTTPServer, StartingHandler


def create_server(host: str, port: int, knowledge_dir: str | None = None):
    """兼容旧调用点（测试与 tools/ 都从这里起服务）。

    不做「先 bind 再建索引」：这条路径的调用方（测试、打包冒烟）需要
    「返回即可用」，中间那段 503 窗口对它们只是噪音。
    """
    return build_app(host, port, knowledge_dir)


def _bound_host(httpd, fallback: str) -> str:
    try:
        return str(httpd.server_address[0])
    except (IndexError, TypeError, AttributeError):
        return fallback


def main() -> int:
    ap = argparse.ArgumentParser(description="记忆文档 Web 服务")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--model", help="临时指定模型（等价于设置 LLM_MODEL）")
    args = ap.parse_args()

    if args.model:
        os.environ["LLM_MODEL"] = args.model

    # 1) 先占端口。端口冲突是最常见的一次性故障，也必须在建索引之前就报出来。
    try:
        httpd = BoundedHTTPServer((args.host, args.port), StartingHandler)
    except OSError as exc:
        if startup.bind_conflict(exc):
            print(f"端口 {args.port} 已被占用。可能已经开着一个实例："
                  f"先关掉它，或换个端口 python -m src.server --port {args.port + 1}",
                  file=sys.stderr)
            return 1
        raise

    # 2) 暴露面校验放在建索引之前：配错了要立刻退出，不能先花两分钟建库再拒绝。
    #    `load_settings()` 很便宜（读一个 json + 环境变量），与 pipeline 内的那次
    #    不共享对象，但两者的取值来自同一份配置。
    settings = load_settings()
    refusal = startup.exposure_refusal(args.host, _bound_host(httpd, args.host),
                                       getattr(settings, "api_keys", "") or "")
    if refusal:
        print(refusal, file=sys.stderr)
        httpd.server_close()
        return 1

    # 3) 起「正在启动」应答器：此刻端口已经在收连接，health 返回 state=starting，
    #    其余请求 503 + Retry-After。客户端不会拿到 ECONNREFUSED。
    threading.Thread(target=httpd.serve_forever, name="startup-answers",
                     daemon=True).start()
    print(f"端口 {args.port} 已监听，正在加载索引…", flush=True)
    try:
        httpd, pipe = build_app(args.host, args.port, server=httpd)
    except BaseException:
        # 建索引失败（语料为空、向量维度不一致）要能把端口还回去，
        # 否则用户重跑一次会得到「端口已被占用」——完全误导的第二个错误。
        httpd.server_close()
        raise

    # 4) 交棒：停掉启动期循环，主线程接管同一个 socket。
    #    `serve_forever()` 末尾会把 shutdown 标志复位，所以可以再进一次；
    #    这两步之间的连接留在内核 backlog 里，客户端只是稍等一下，不会失败。
    httpd.shutdown()
    print(f"serving http://{args.host}:{args.port}  "
          f"model={pipe.settings.model} base={pipe.settings.api_base}")
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
