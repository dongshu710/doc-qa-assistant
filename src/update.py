"""检查 GitHub 上有没有新版本。

只查不装：这里不做自我改写，也不下载覆盖正在运行的文件。原因很直接——
服务正在用的 .py 被替换掉，下一次 import 就会半新半旧，出问题也难查。
所以这里只回答三件事：有没有新版、新版是什么、去哪下载。

网络是不可靠的，所以：4 秒超时、失败即降级、结果缓存 10 分钟。
未认证的 GitHub API 每小时只有 60 次，缓存不是为了快，是为了不被限流。
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

APP_ASSET = "zhiyuan-app-{version}.zip"
PLUGIN_ASSET = "zhiyuan-plugin-{version}.zip"

CACHE_TTL = 600           # 秒；点「检查更新」是低频操作，10 分钟足够
TIMEOUT = 4.0
UA = "zhiyuan-updater"

_cache: dict[str, dict] = {}
_lock = threading.Lock()


def asset_names(version: str) -> dict[str, str]:
    return {"app": APP_ASSET.format(version=version),
            "plugin": PLUGIN_ASSET.format(version=version)}


def repo_slug(repo_url: str) -> str:
    """从 https://github.com/owner/name 取 owner/name；取不到返回空串。"""
    match = re.search(r"github\.com[/:]([^/]+)/([^/\s#?]+?)(?:\.git)?/?$", (repo_url or "").strip())
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.15.0' / '1.15.0' → (1, 15, 0)。非数字段落一律当 0，不抛异常。"""
    parts = re.findall(r"\d+", (text or "").lstrip("vV"))
    return tuple(int(p) for p in parts[:3]) or (0,)


def is_newer(latest: str, current: str) -> bool:
    left, right = parse_version(latest), parse_version(current)
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


def release_url(repo_url: str, tag: str = "") -> str:
    base = (repo_url or "").rstrip("/")
    if not base:
        return ""
    return f"{base}/releases/tag/{tag}" if tag else f"{base}/releases/latest"


def _fetch_latest(slug: str, timeout: float) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{slug}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def check(current: str, repo_url: str = "", *, force: bool = False,
          fetch=None, now: float | None = None, timeout: float = TIMEOUT) -> dict:
    """返回给页面直接渲染的字典，永远不抛异常。

    fetch 可注入（测试用），签名 fetch(slug, timeout) -> dict。
    """
    slug = repo_slug(repo_url)
    stamp = time.time() if now is None else now
    payload: dict = {
        "ok": False,
        "current": current,
        "latest": "",
        "has_update": False,
        "url": release_url(repo_url),
        "published_at": "",
        "notes": "",
        "assets": [],
        "downloads": {},
        "checked_at": datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds"),
        "cached": False,
        "message": "",
    }
    if not slug:
        payload["message"] = "不知道仓库地址（.git/config 里没有 origin），只能手动去看发布页"
        return payload

    key = f"{slug}@{current}"
    with _lock:
        hit = _cache.get(key)
        if hit and not force and stamp - hit["at"] < CACHE_TTL:
            fresh = dict(hit["data"])
            fresh["cached"] = True
            return fresh

    try:
        data = (fetch or _fetch_latest)(slug, timeout)
    except urllib.error.HTTPError as exc:
        code = getattr(exc, "code", 0)
        payload["message"] = ("GitHub 返回 404：仓库还没发过 Release" if code == 404
                              else f"GitHub 返回 {code}，稍后再试")
        return payload
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        payload["message"] = f"连不上 GitHub（{reason}）：可能离线，或被代理拦住"
        return payload
    except (ValueError, KeyError, TypeError, AttributeError):
        payload["message"] = "GitHub 返回的内容看不懂，可能被网关改写了"
        return payload
    except Exception as exc:  # noqa: BLE001 —— 更新检查出任何岔子都不能把设置面板拖垮
        payload["message"] = f"检查更新时出错：{type(exc).__name__}: {exc}"
        return payload

    if not isinstance(data, dict):
        # 代理返回错误页 JSON、或网关塞了个数组，都当「看不懂」处理
        payload["message"] = "GitHub 返回的内容看不懂，可能被网关改写了"
        return payload

    tag = str(data.get("tag_name") or "")
    latest = tag.lstrip("vV")
    if not latest:
        payload["message"] = "Release 里没有版本号"
        return payload

    body = str(data.get("body") or "").strip()
    assets = [{"name": str(a.get("name") or ""), "size": int(a.get("size") or 0),
               "url": str(a.get("browser_download_url") or "")}
              for a in (data.get("assets") or []) if a.get("name")]
    by_name = {a["name"]: a for a in assets}
    names = asset_names(latest)

    payload.update({
        "ok": True,
        "latest": latest,
        "has_update": is_newer(latest, current),
        "url": release_url(repo_url, tag or f"v{latest}"),
        "published_at": str(data.get("published_at") or "")[:10],
        # Release 正文是整篇 CHANGELOG 段落，页面只放前 400 字，避免把抽屉撑爆
        "notes": body[:400],
        "assets": assets,
        "downloads": {
            "app": (by_name.get(names["app"]) or {}).get("url", ""),
            "plugin": (by_name.get(names["plugin"]) or {}).get("url", ""),
        },
        "message": "",
    })
    with _lock:
        _cache[key] = {"at": stamp, "data": payload}
    return payload


def clear_cache() -> None:
    """测试用：避免上一个用例的缓存串到下一个。"""
    with _lock:
        _cache.clear()
