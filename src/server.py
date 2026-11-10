"""最小可用 Web 服务入口。

  python -m src.server --port 8000

路由与实现已经按职责拆到 `src/handlers/`：
  base.py       HTTP 基类（响应、来源闸门、鉴权、通用动作）
  resources.py  笔记 / 会话 / 文件 / 存储 / 设置
  read.py       页面与只读 API
  write.py      问答 / 知识库 / 设置 / 评测用例
  app.py        组合根（依赖装配 + Handler 拼装）
本文件只保留命令行入口与向后兼容的 `create_server`。
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import sys

from .handlers.app import build_app


def _loopback_only(host: str) -> bool:
    """`--host` 给的是不是只对本机可见。

    主机名一律按「对外」处理：它可能解析到任意地址，按名字判断等于给自己留后门。
    空串等同 localhost（http.server 的惯例）。
    """
    text = (host or "").strip().lower()
    if text in ("", "localhost", "localhost."):
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


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
        # 端口占用是个人使用最常见的一次性故障，报错误码等于没说。
        # Windows 上 http.server 带 SO_REUSEADDR，冲突时抛的是 10013（errno 13）
        # 而不是直觉里的 10048，两个都要认，否则提示形同虚设。
        text = str(exc).lower()
        busy = (getattr(exc, "errno", None) in (13, 48, 98, 10013, 10048)
                or "already in use" in text or "10013" in text or "10048" in text)
        if busy:
            print(f"端口 {args.port} 已被占用。可能已经开着一个实例："
                  f"先关掉它，或换个端口 python -m src.server --port {args.port + 1}",
                  file=sys.stderr)
            return 1
        raise

    # 监听非回环地址 = 局域网其它机器能连上。此时如果没有 API_KEYS，就是全库敞开：
    # Host 校验看的是请求头，攻击者自己填一个 host.docker.internal 就过了。
    # 这条校验放在绑定端口之后、开始服务之前，是为了让「端口被占用」先报出来
    # （那是个更常见的一次性故障），失败时记得把端口还回去。
    keys = getattr(pipe.settings, "api_keys", "") or ""
    if not _loopback_only(args.host) and not keys.strip():
        print(
            f"[拒绝启动] --host {args.host} 会让局域网其它机器连上，而 API_KEYS 为空（等于不鉴权）。\n"
            "  Host 校验挡不住这个：它看的是请求头，任何人都能填成 host.docker.internal。\n"
            "  两种改法：\n"
            "    1) 只在本机用：去掉 --host（默认就是 127.0.0.1）\n"
            "    2) 要给容器访问：同时设 API_KEYS，例如\n"
            "         set API_KEYS=<一串随机字符>   （PowerShell: $env:API_KEYS='...'）\n"
            "        然后 Dify 里「外部知识库 API」的 Key 填同一个值。",
            file=sys.stderr)
        httpd.server_close()
        return 1

    print(f"serving http://{args.host}:{args.port}  model={pipe.settings.model} base={pipe.settings.api_base}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())