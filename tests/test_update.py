"""更新检查的可执行单测：版本比较、缓存、离线降级。

直接跑：python tests/test_update.py
不联网：fetch 全部注入假实现，唯一的网络分支靠抛异常模拟。
"""
from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import update  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"PASS {name}")
    else:
        FAIL += 1
        print(f"FAIL {name}  {detail}")


def fake_release(version: str = "1.16.0", **over):
    names = update.asset_names(version)
    data = {
        "tag_name": f"v{version}",
        "published_at": "2026-11-01T09:30:00Z",
        "body": "## 新增\n- 更新按钮\n\n" + "x" * 600,
        "assets": [
            {"name": names["app"], "size": 700_000,
             "browser_download_url": f"https://example.test/dl/{names['app']}"},
            {"name": names["plugin"], "size": 120_000,
             "browser_download_url": f"https://example.test/dl/{names['plugin']}"},
        ],
    }
    data.update(over)
    return data


def test_versions() -> None:
    check("解析 v1.15.0", update.parse_version("v1.15.0") == (1, 15, 0))
    check("解析空串不抛", update.parse_version("") == (0,))
    check("解析 1.15", update.parse_version("1.15") == (1, 15))
    check("1.16 比 1.15 新", update.is_newer("1.16.0", "1.15.0"))
    check("1.15.1 比 1.15 新", update.is_newer("1.15.1", "1.15"))
    check("同版本不算新", not update.is_newer("v1.15.0", "1.15.0"))
    check("旧版本不算新", not update.is_newer("1.14.9", "1.15.0"))
    check("跨大版本", update.is_newer("2.0.0", "1.99.99"))


def test_repo() -> None:
    check("https 地址", update.repo_slug("https://github.com/dongshu710/doc-qa-assistant")
          == "dongshu710/doc-qa-assistant")
    check("ssh 地址去 .git", update.repo_slug("git@github.com:owner/name.git") == "owner/name")
    check("带尾斜杠", update.repo_slug("https://github.com/a/b/") == "a/b")
    check("非 GitHub 返回空", update.repo_slug("https://gitlab.com/a/b") == "")
    check("空串返回空", update.repo_slug("") == "")


def test_assets() -> None:
    names = update.asset_names("1.15.0")
    check("应用包名", names["app"] == "zhiyuan-app-1.15.0.zip")
    check("插件包名", names["plugin"] == "zhiyuan-plugin-1.15.0.zip")


def test_success() -> None:
    update.clear_cache()
    calls = []

    def fetch(slug, timeout):
        calls.append(slug)
        return fake_release()

    data = update.check("1.15.0", "https://github.com/a/b", fetch=fetch, now=1000)
    check("查询成功", data["ok"] is True, str(data.get("message")))
    check("识别有新版", data["has_update"] is True)
    check("最新版号去掉 v", data["latest"] == "1.16.0")
    check("发布日期只留日期", data["published_at"] == "2026-11-01")
    check("正文截断到 400 字", len(data["notes"]) == 400, str(len(data["notes"])))
    check("应用包直链", data["downloads"]["app"].endswith("zhiyuan-app-1.16.0.zip"))
    check("插件包直链", data["downloads"]["plugin"].endswith("zhiyuan-plugin-1.16.0.zip"))
    check("说明页带 tag", data["url"].endswith("/releases/tag/v1.16.0"), data["url"])
    check("只请求一次", len(calls) == 1)

    # 同一版本在缓存期内再点一次：不该再打 GitHub（未认证额度只有 60 次/小时）
    data2 = update.check("1.15.0", "https://github.com/a/b", fetch=fetch, now=1001)
    check("缓存命中", data2["cached"] is True and len(calls) == 1)
    data3 = update.check("1.15.0", "https://github.com/a/b", fetch=fetch, now=1001, force=True)
    check("强制刷新绕过缓存", data3["cached"] is False and len(calls) == 2)
    data4 = update.check("1.15.0", "https://github.com/a/b", fetch=fetch, now=5000)
    check("缓存过期后重查", len(calls) == 3)


def test_same_version() -> None:
    update.clear_cache()
    data = update.check("1.16.0", "https://github.com/a/b",
                        fetch=lambda slug, timeout: fake_release("1.16.0"))
    check("同版本判定无更新", data["ok"] and data["has_update"] is False)


def test_offline() -> None:
    update.clear_cache()

    def boom(slug, timeout):
        raise urllib.error.URLError("getaddrinfo failed")

    data = update.check("1.15.0", "https://github.com/a/b", fetch=boom)
    check("离线不抛异常", data["ok"] is False)
    check("离线说明能看懂", "连不上 GitHub" in data["message"], data["message"])
    check("离线仍给发布页", data["url"].endswith("/releases/latest"), data["url"])


def test_http_404() -> None:
    update.clear_cache()

    def not_found(slug, timeout):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    data = update.check("1.15.0", "https://github.com/a/b", fetch=not_found)
    check("404 提示没发过 Release", data["ok"] is False and "还没发过 Release" in data["message"])


def test_bad_payload() -> None:
    update.clear_cache()
    data = update.check("1.15.0", "https://github.com/a/b",
                        fetch=lambda slug, timeout: {"assets": []})
    check("缺版本号不崩", data["ok"] is False and data["message"], data["message"])

    update.clear_cache()
    data = update.check("1.15.0", "https://github.com/a/b",
                        fetch=lambda slug, timeout: ["不是字典"])
    check("返回类型离谱也不崩", data["ok"] is False)

    update.clear_cache()

    def crash(slug, timeout):
        raise RuntimeError("谁都没想到")

    data = update.check("1.15.0", "https://github.com/a/b", fetch=crash)
    check("未知异常也不崩", data["ok"] is False and "RuntimeError" in data["message"],
          data["message"])


def test_no_repo() -> None:
    update.clear_cache()
    data = update.check("1.15.0", "")
    check("没仓库地址也能答", data["ok"] is False and "仓库地址" in data["message"])
    check("没仓库地址不给死链", data["url"] == "")


def main() -> int:
    for fn in (test_versions, test_repo, test_assets, test_success, test_same_version,
               test_offline, test_http_404, test_bad_payload, test_no_repo):
        fn()
    print(f"\n通过 {PASS}，失败 {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
