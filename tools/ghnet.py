#!/usr/bin/env python3
"""给发布工具选一条能通的网络路径。

背景（本机实测）：`github.com:443` 直连会被重置，而 `api.github.com` 直连可用；
同时本机代理（127.0.0.1 上的工具）会间歇性返回 `502 Bad Gateway`。
发布时恰好两个都碰上，就会得到「昨天还能发，今天发不出去」这种最难排查的失败。

做法：启动时探一次 `/rate_limit`，先直连、失败再退回系统代理，选中的那条路缓存复用。
不写死直连，是因为有些网络（公司出口）只有代理能出去。
"""
from __future__ import annotations

import urllib.error
import urllib.request

PROBE = "https://api.github.com/rate_limit"
_OPENER = None


def _try(opener, timeout: float) -> bool:
    req = urllib.request.Request(PROBE, headers={"User-Agent": "jiyi-release"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def opener(force: str = ""):
    """返回可用的 opener；`force=direct|proxy` 可跳过探测（排查时用）。"""
    global _OPENER
    if _OPENER is not None and not force:
        return _OPENER
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    proxied = urllib.request.build_opener()
    if force == "direct":
        _OPENER = direct
    elif force == "proxy":
        _OPENER = proxied
    elif _try(direct, 8):
        _OPENER = direct
    elif _try(proxied, 12):
        _OPENER = proxied
    else:
        # 两条都不通就交给直连：让调用方看到真正的连接错误，而不是被包一层
        _OPENER = direct
    return _OPENER
