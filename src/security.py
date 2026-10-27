"""请求来源校验：本机服务也不等于「谁都能碰」。

威胁模型（只在个人电脑单机运行）：

1. **CSRF**：用户在浏览器里打开任意页面，那个页面可以 POST 到 `127.0.0.1`。
   从服务端看，对端 IP 就是本机，所以「是不是本机」永远判真——用 IP 当身份是错的。
   写操作必须能证明「不是跨站发起的」。
2. **DNS rebinding**：攻击者把域名解析到 127.0.0.1，页面与 API 就成了「同源」，
   这时连 GET 的响应都能被读走。所以要校验 Host，而不是只看 Origin。
3. **表单/no-cors 绕过**：`<form>` 与 `fetch(mode:'no-cors')` 能发 POST，但只能带
   `text/plain` / `urlencoded` / `multipart`。而我们只解析 JSON，
   所以「带 body 的写请求必须是 application/json」本身就是一道闸。

放行原则：**不拦非浏览器客户端**。curl、SDK、MCP 不会带 Origin / Sec-Fetch-Site，
它们本来就不受同源策略约束，拦了只会让接入变难。
"""
from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit

LOOPBACK_NAMES = {"localhost", "localhost."}
REASONS = {
    "host": "只接受本机访问（Host 不合法）；需要局域网访问请设置 ALLOWED_HOSTS",
    "origin": "拒绝跨站请求（Origin 不属于本机）",
    "fetch_site": "拒绝跨站请求（Sec-Fetch-Site 表明来自其他站点）",
    "client_header": "缺少站内请求标记（X-Jiyi-Client），已拒绝",
    "content_type": "写请求必须是 application/json（浏览器表单与 text/plain 一律拒绝）",
}
CLIENT_HEADER = "X-Jiyi-Client"
CLIENT_VALUE = "web"


def _extra_hosts() -> set[str]:
    raw = (os.environ.get("ALLOWED_HOSTS") or "").strip()
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _hostname(value: str) -> str:
    """从 `Host` / `Origin` / URL 里取主机名；异常输入返回空串。"""
    text = (value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "//" + text
    try:
        host = urlsplit(text).hostname or ""
    except ValueError:
        return ""
    return host.lower()


def host_allowed(host_header: str, extra: set[str] | None = None) -> bool:
    """Host 必须是回环地址，或显式写进 ALLOWED_HOSTS 的主机名/IP。"""
    host = _hostname(host_header)
    if not host:
        return False
    if host in LOOPBACK_NAMES:
        return True
    try:
        if ipaddress.ip_address(host).is_loopback:
            return True
    except ValueError:
        pass
    return host in (extra if extra is not None else _extra_hosts())


def origin_allowed(origin: str, extra: set[str] | None = None) -> bool:
    """有 Origin 就必须是本机来源；没有 Origin（非浏览器）直接放行。"""
    if not (origin or "").strip():
        return True
    return host_allowed(origin, extra)


def site_allowed(value: str) -> bool:
    """Sec-Fetch-Site：same-origin / none 可放行；cross-site / same-site 拒绝。"""
    site = (value or "").strip().lower()
    return site in ("", "same-origin", "none")


def content_type_allowed(value: str, has_body: bool) -> bool:
    if not has_body:
        return True
    base = (value or "").split(";")[0].strip().lower()
    return base == "application/json"


def looks_like_browser(headers) -> bool:
    """有 Origin 或 Sec-Fetch-Site 就是浏览器发的；curl / SDK 两者都不会带。"""
    return bool((headers.get("Origin") or "").strip()
                or (headers.get("Sec-Fetch-Site") or "").strip())


def client_header_ok(headers) -> bool:
    """浏览器写请求必须带站内标记；非浏览器不强制，免得接入方被迫伪造。"""
    if not looks_like_browser(headers):
        return True
    return (headers.get(CLIENT_HEADER) or "").strip().lower() == CLIENT_VALUE


def write_problem(headers, has_body: bool = True, extra: set[str] | None = None) -> str:
    """写请求的来源校验：返回拒绝原因，空串表示通过。

    headers 只要有 `get` 即可（`http.client.HTTPMessage` 或普通 dict 都行）。
    """
    if not host_allowed(headers.get("Host") or "", extra):
        return "host"
    if not origin_allowed(headers.get("Origin") or "", extra):
        return "origin"
    if not site_allowed(headers.get("Sec-Fetch-Site") or ""):
        return "fetch_site"
    if not client_header_ok(headers):
        return "client_header"
    if not content_type_allowed(headers.get("Content-Type") or "", has_body):
        return "content_type"
    return ""


def read_problem(headers, extra: set[str] | None = None) -> str:
    """读请求只校验 Host：挡 DNS rebinding，同时不打断正常浏览。"""
    if not host_allowed(headers.get("Host") or "", extra):
        return "host"
    return ""
