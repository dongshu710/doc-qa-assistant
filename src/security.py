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

# `host.docker.internal` 是 Docker 给「宿主机」的保留名，语义上就是本机。
# 把它算作回环别名，是为了让 Dify 这类跑在容器里、要访问本服务的平台开箱能用，
# 不必每次启动都带 ALLOWED_HOSTS。
#
# 为什么这不放宽攻击面：这个域名由 Docker 的 DNS 提供，公网无法注册同名域名，
# DNS rebinding 也借不到它；浏览器发起的请求仍然要过 Origin / Sec-Fetch-Site /
# X-Jiyi-Client 三道校验。真正需要防备的是「任意域名解析到 127.0.0.1」，
# 而这里的做法是把一个不可被外部控制的保留名加进白名单，不是放开域名任意解析。
#
# **但 Host 是请求头，不是身份。** 任何人都能手工发 `Host: host.docker.internal`，
# 所以这一票放行只能保证「合法客户端不被误拦」，它**不构成访问控制**。
# 一旦监听非回环地址（--host 0.0.0.0），唯一拦住局域网的是 API_KEYS；
# 两者缺一，整个库就是敞开的。启动校验见 src/server.py::main。
DOCKER_HOST_NAMES = {"host.docker.internal", "gateway.docker.internal"}
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
    if host in LOOPBACK_NAMES or host in DOCKER_HOST_NAMES:
        return True
    try:
        if ipaddress.ip_address(host).is_loopback:
            return True
    except ValueError:
        pass
    return host in (extra if extra is not None else _extra_hosts())


def _origin_port(origin: str) -> int | None:
    try:
        parts = urlsplit(origin)
        if parts.port:
            return parts.port
    except ValueError:
        return None
    scheme = ""
    try:
        scheme = urlsplit(origin).scheme.lower()
    except ValueError:
        return None
    return {"http": 80, "https": 443}.get(scheme)


def _host_port(host_header: str, default: int) -> int | None:
    try:
        parts = urlsplit("//" + (host_header or "").strip())
    except ValueError:
        return None
    return parts.port if parts.port is not None else default


def origin_allowed(origin: str, extra: set[str] | None = None,
                   host_header: str = "") -> bool:
    """有 Origin 就必须是本机来源；没有 Origin（非浏览器）直接放行。

    只比主机名是不够的：`http://localhost:9999` 与 `:8011` 主机名相同、端口不同，
    是两个源。浏览器侧真正把我们兜住的是 `X-Jiyi-Client`（跨源自定义头会触发
    预检，预检会被这里的 Origin 判据拦下），但那是「第二道锁」，不该拿它当唯一依据。

    `host_header` 为空时退回旧行为（只比主机），供单独调用的场景与旧测试使用；
    服务端的写路径一定会把 `Host` 传进来。

    反代场景不按端口比：外部域名通常写在 `ALLOWED_HOSTS` 里，端口在代理那层已经
    改写过（443 → 内部 8000），硬比会把正常部署判成跨站。
    """
    if not (origin or "").strip():
        return True
    if not host_allowed(origin, extra):
        return False
    if not (host_header or "").strip():
        return True
    origin_host = _hostname(origin)
    if origin_host not in LOOPBACK_NAMES:
        try:
            if not ipaddress.ip_address(origin_host).is_loopback:
                return True      # 走 ALLOWED_HOSTS 的域名：端口交给代理
        except ValueError:
            return True
    want = _origin_port(origin)
    got = _host_port(host_header, 443 if want == 443 else 80)
    return want is not None and want == got


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
    if not origin_allowed(headers.get("Origin") or "", extra,
                          host_header=headers.get("Host") or ""):
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

# ---------- 反代：谁才是「来访者」 ----------
#
# 单机场景「对端是回环 = 管理员」成立，因为能连上 127.0.0.1 的只有本机进程。
# 一旦前面挂了反向代理，对端永远是 127.0.0.1——于是**任何能访问代理的人**
# 都会通过 `_is_admin()`：`/metrics`、`/api/audit`、知识库审批全开。
# 这不是配置问题，是把「网络位置」当「身份」的必然后果。
#
# 修法不是「默认不信代理」（那会让正常部署立刻失效），而是把这件事显式化：
#   TRUST_PROXY=on          才读 X-Forwarded-For，且只认 TRUSTED_PROXIES 发来的
#   ADMIN_ALLOW_REMOTE=1    才允许「不是直连本机」的地址行使管理员权限
# 两个开关默认都关：不配置 = 行为与以前完全一致；配错也不会比现在更开放。

LOOPBACK_IPS = frozenset({"127.0.0.1", "::1"})


def trust_proxy() -> bool:
    # 变量名写成字面量而不是拼字符串：`tools/gen_env_example.py` 靠正则扫
    # `os.environ.get("字面量")` 生成文档，拼出来的一律扫不到，等于没文档。
    return (os.environ.get("TRUST_PROXY") or "").strip().lower() in ("1", "on", "true", "yes")


def admin_allow_remote() -> bool:
    return (os.environ.get("ADMIN_ALLOW_REMOTE") or "").strip().lower() in ("1", "on", "true", "yes")


def _canonical_ip(text: str) -> str | None:
    """把 `1.2.3.4`、`1.2.3.4:5678`、`[::1]:443`、`::1` 规范成可比较的字符串。

    不是 IP 就返回 None：X-Forwarded-For 是客户端可写的头，里面塞 `unknown`、
    `_hidden`、甚至一段 HTML 都是常事，不能让它进审计日志的 client 字段。
    """
    value = (text or "").strip()
    if not value:
        return None
    if value.startswith("["):                       # [::1]:443
        value = value[1:].split("]", 1)[0]
    elif value.count(":") == 1 and "." in value:    # 1.2.3.4:5678
        value = value.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def trusted_proxies() -> set[str]:
    """可信代理地址；默认只信本机（nginx/traefik 与本服务同机部署是最常见形态）。"""
    raw = (os.environ.get("TRUSTED_PROXIES") or "").strip()
    if not raw:
        return set(LOOPBACK_IPS)
    out = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        out.add(_canonical_ip(item) or item.lower())
    return out


def client_ip(peer: str, forwarded_for: str) -> tuple[str, bool]:
    """返回 `(客户端地址, 是否来自可信代理的 X-Forwarded-For)`。

    从右往左跳过可信代理：XFF 是逐跳追加的，最左边那一段是客户端自己填的，
    直接取最左等于让来访者给自己写身份。最右那个「不认识的地址」才是最后一个
    代理看到的对端。

    `TRUST_PROXY` 关闭或对端不是可信代理时，XFF 一概不看——否则从局域网直连
    过来的人随手加一个头就能把审计日志里的来源改成别人。
    """
    peer_ip = _canonical_ip(peer) or (peer or "").strip() or "unknown"
    if not trust_proxy():
        return peer_ip, False
    hops = [h for h in (forwarded_for or "").split(",") if h.strip()]
    if not hops:
        return peer_ip, False
    trusted = trusted_proxies()
    if peer_ip not in trusted:
        return peer_ip, False
    for hop in reversed(hops):
        addr = _canonical_ip(hop)
        if addr and addr not in trusted:
            return addr, True
    # 整条链都是我们自己的代理：说不清真实客户端，退回对端，但仍标记「经过代理」
    return peer_ip, True


def admin_by_ip(ip: str, via_proxy: bool = False) -> bool:
    """没有管理员令牌时，按地址判定管理员。

    - 直连本机（不是代理转进来的）：是管理员。这是单机形态的默认体验。
    - 经过代理、或地址不是回环：**必须显式 `ADMIN_ALLOW_REMOTE=1`**。

    为什么要区分「回环」与「经代理的回环」：反代下两者都是 127.0.0.1，
    但只有前者能证明操作者就在这台机器前。`ADMIN_ALLOW_REMOTE=1` 的含义是
    「这个端口前面的所有来访者我都认作管理员」——把它打开前请确认代理自己
    做了认证，否则等于把审批权交给整个网络。
    """
    loopback = _canonical_ip(ip) in LOOPBACK_IPS
    if loopback and not via_proxy:
        return True
    return admin_allow_remote()
