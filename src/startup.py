"""启动期校验：这些判断错了不会报错，只会静默地把整个库暴露出去。

为什么单独成模块：`server.py` 有一条门禁「只剩入口，≤120 行」。校验逻辑与几百字
的提示文案留在入口里，入口很快会长成第二个巨型文件——而它恰恰是最该保持一眼看完的地方。
这里只放纯函数，不 import httpd，也不打印（由入口决定往哪儿写）。
"""
from __future__ import annotations

import ipaddress

from .auth import ApiKeyStore

_BUSY_ERRNOS = (13, 48, 98, 10013, 10048)


def loopback_only(host: str) -> bool:
    """`--host` 给的是不是只对本机可见。

    主机名一律按「对外」处理：它可能解析到任意地址，按名字判断等于给自己留后门。

    空串**不是** localhost。这里原来写的是「空串等同 localhost（http.server 的惯例）」，
    但 `socket.bind(("", port))` 的真实语义是绑到通配地址——实测
    `python -m src.server --host ""` 会 LISTENING 0.0.0.0，而这条函数返回 True
    让「非回环必须配 API_KEYS」的校验直接跳过，整库对局域网敞开。
    所以空串按对外处理，交给拒启分支。
    """
    text = (host or "").strip().lower()
    if not text:
        return False
    if text in ("localhost", "localhost."):
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def bind_conflict(exc: OSError) -> bool:
    """端口被占用。Windows 上抛的是 10013 而不是直觉里的 10048，两个都要认。"""
    text = str(exc).lower()
    return (getattr(exc, "errno", None) in _BUSY_ERRNOS
            or "already in use" in text or "10013" in text or "10048" in text)


def exposure_refusal(host: str, bound_host: str, api_keys: str) -> str | None:
    """监听非回环且没有一把有效 Key 时，返回拒启提示；否则返回 None。

    判据是「解析出了至少一把 Key」，不是「字符串非空」：
    `API_KEYS=,`（或 `:`、`,,`）能通过 `.strip()` 检查，但 ApiKeyStore 会跳过所有空条目
    ——实测 `ApiKeyStore(",").enabled == False`，于是启动校验通过、鉴权却全放行，
    服务"以为配了 Key"，日志里也不会有任何提示。

    同时复核内核实际绑定地址：`args.host` 与真实绑定之间可能有偏差
    （空串 → 通配地址就是一个例子），这道检查只信 socket。
    """
    exposed = not loopback_only(host) or not loopback_only(bound_host)
    if not exposed or ApiKeyStore(api_keys or "").enabled:
        return None
    shown = bound_host or host
    return (
        f"[拒绝启动] 当前会监听 {shown}，局域网其它机器能连上，"
        "而 API_KEYS 里没有解析出任何一把有效 Key（等于不鉴权）。\n"
        "  Host 校验挡不住这个：它看的是请求头，任何人都能填成 host.docker.internal。\n"
        "  三种改法：\n"
        "    1) 只在本机用：去掉 --host（默认就是 127.0.0.1）\n"
        "    2) 要给容器/局域网访问：同时设 API_KEYS，例如\n"
        "         set API_KEYS=<一串随机字符>   （PowerShell: $env:API_KEYS='...'）\n"
        "        然后 Dify 里「外部知识库 API」的 Key 填同一个值。\n"
        "    3) 多个 Key 用英文逗号分隔，格式 名字:密钥:ro|rw|admin；\n"
        "       只写逗号或冒号会被当作「没有 Key」，不会启动。"
    )
