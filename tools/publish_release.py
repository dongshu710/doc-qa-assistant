#!/usr/bin/env python3
"""把 dist 里的发布包发到 GitHub Release（零第三方依赖）。

用法：
    python tools/publish_release.py --tag v1.12.0
    python tools/publish_release.py --all            # dist 里有包、远端还没建 Release 的版本
    python tools/publish_release.py --tag v1.12.0 --dry-run

凭据：优先读环境变量 GITHUB_TOKEN / GH_TOKEN；没有就复用 git 凭据管理器里推代码用的那份，
不额外要求用户再配一次令牌。

设计取舍：Release 正文直接从 CHANGELOG 摘，不另写一份，避免两处描述走样。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
CHANGELOG = ROOT / "CHANGELOG.md"
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
TIMEOUT = 90


def say(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str) -> "None":
    print(f"错误：{msg}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def read_version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def repo_slug() -> str:
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        die("读不到 origin 远程地址，请确认在仓库根目录执行")
    m = re.search(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?$", url)
    if not m:
        die(f"origin 不是 GitHub 地址：{url}")
    return f"{m.group(1)}/{m.group(2)}"


def token() -> str:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    # 复用 git 已存凭据：用户推过代码就有，不必再单独准备令牌
    try:
        out = subprocess.run(["git", "credential", "fill"], cwd=ROOT, text=True,
                             capture_output=True, timeout=20,
                             input="protocol=https\nhost=github.com\n\n").stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        out = ""
    for line in out.splitlines():
        if line.startswith("password="):
            return line[len("password="):].strip()
    die("没有可用令牌：请设置 GITHUB_TOKEN，或先确认 git 能推送代码")


def api(method: str, path: str, payload: dict | None = None) -> tuple[int, object]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", f"token {token()}")
    req.add_header("Accept", "application/vnd.github+json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(body) if body.strip() else None)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"message": body[:300]}
    except urllib.error.URLError as exc:
        die(f"连不上 GitHub：{exc.reason}")


def changelog_body(version: str) -> str:
    if not CHANGELOG.exists():
        return ""
    text = CHANGELOG.read_text(encoding="utf-8")
    # 从 "## [x.y.z]" 取到下一个二级标题，段落原样搬进 Release
    pattern = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)",
                         re.MULTILINE | re.DOTALL)
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def asset_paths(version: str) -> list[Path]:
    """三个包一起发：应用包、插件包、技能包。"""
    return [DIST / f"jiyi-app-{version}.zip",
            DIST / f"jiyi-plugin-{version}.zip",
            DIST / f"jiyi-skill-{version}.zip"]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_body(version: str, slug: str, digests: dict[str, str]) -> str:
    parts = [changelog_body(version) or f"版本 {version}。"]
    parts.append("---")
    base = f"https://github.com/{slug}/releases/download/v{version}"
    rows = [
        ("应用包", "文档问答 + 笔记，解压后 `start.bat` / `start.sh` 启动", f"jiyi-app-{version}.zip"),
        ("插件包", "只有笔记能力，挂到任意 MCP 客户端（stdio）", f"jiyi-plugin-{version}.zip"),
        ("技能包", "`jiyi-files` 技能，解压进 `~/.workbuddy/skills/` 即装", f"jiyi-skill-{version}.zip"),
    ]
    table = ["## 下载", "", "| 包 | 内容 | 文件 |", "|---|---|---|"]
    for label, desc, name in rows:
        table.append(f"| **{label}** | {desc} | [`{name}`]({base}/{name}) |")
    parts.append("\n".join(table))
    if digests:
        block = "\n".join(f"{digest}  {name}" for name, digest in digests.items())
        parts.append(f"```\n{block}\n```")
    parts.append(f"完整变更见 [CHANGELOG.md](https://github.com/{slug}/blob/main/CHANGELOG.md)。")
    return "\n\n".join(parts)


def find_release(slug: str, tag: str) -> dict | None:
    status, data = api("GET", f"/repos/{slug}/releases/tags/{tag}")
    if status == 200 and isinstance(data, dict):
        return data
    if status == 404:
        return None
    die(f"查询 Release 失败（HTTP {status}）：{data}")


def upload_asset(slug: str, release_id: int, path: Path) -> bool:
    url = f"{UPLOADS}/repos/{slug}/releases/{release_id}/assets?name={urllib.parse.quote(path.name)}"
    payload = path.read_bytes()
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"token {token()}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/zip")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        say(f"  附件上传失败（HTTP {exc.code}）：{detail}")
        return False
    except urllib.error.URLError as exc:
        say(f"  附件上传失败：{exc.reason}")
        return False


def delete_asset(slug: str, asset_id: int) -> bool:
    status, data = api("DELETE", f"/repos/{slug}/releases/assets/{asset_id}")
    if status != 204:
        say(f"  旧附件删除失败（HTTP {status}）：{data}")
        return False
    return True


def publish(slug: str, tag: str, dry_run: bool, with_asset: bool, replace: bool = False) -> bool:
    version = tag.lstrip("v")
    paths = [p for p in asset_paths(version) if p.exists()]
    digests = {p.name: sha256_of(p) for p in paths}
    body = build_body(version, slug, digests)
    existing = find_release(slug, tag)

    if dry_run:
        say(f"[dry-run] {tag}：release={'已存在' if existing else '将创建'}，"
            f"附件 {len(paths)} 个（{', '.join(p.name for p in paths) or '无'}）")
        say(f"[dry-run] 正文 {len(body)} 字符，前 80 字：{body[:80]!r}")
        return True

    if existing:
        status, data = api("PATCH", f"/repos/{slug}/releases/{existing['id']}",
                           {"body": body, "name": f"{tag}"})
        if status != 200:
            say(f"  更新 Release 失败（HTTP {status}）：{data}")
            return False
        release_id = existing["id"]
        say(f"{tag}：Release 已存在，正文已同步")
    else:
        status, data = api("POST", f"/repos/{slug}/releases", {
            "tag_name": tag,
            "name": tag,
            "body": body,
            "draft": False,
            "prerelease": False,
        })
        if status not in (200, 201):
            say(f"  创建 Release 失败（HTTP {status}）：{data}")
            return False
        release_id = data["id"]
        say(f"{tag}：Release 已创建")

    if not with_asset or not paths:
        return True

    for path in paths:
        old = next((a for a in (existing or {}).get("assets", []) if a["name"] == path.name), None)
        if old and not replace:
            say(f"  附件已存在，跳过：{path.name}")
            continue
        if old:
            if not delete_asset(slug, old["id"]):
                return False
            say(f"  已删除旧附件：{path.name}")
        ok = upload_asset(slug, release_id, path)
        say(f"  附件 {'上传完成' if ok else '未上传'}：{path.name}"
            f"（{path.stat().st_size // 1024} KB）")
        if not ok:
            return False
    return True


def version_key(tag: str) -> tuple[int, ...]:
    return tuple(int(part) if part.isdigit() else 0 for part in tag.lstrip("v").split("."))


def ensure_latest(slug: str, tags: list[str]) -> None:
    """GitHub 把 latest 默认给「最后创建的」release，批量补历史版本会把最新版挤下去，
    /releases/latest/download/ 随之 404。这里显式指回版本号最高的那个，只升不降。"""
    if not tags:
        return
    newest = max(tags, key=version_key)
    status, data = api("GET", f"/repos/{slug}/releases/latest")
    current = data.get("tag_name", "") if status == 200 and isinstance(data, dict) else ""
    if current and version_key(current) >= version_key(newest):
        return
    release = find_release(slug, newest)
    if not release:
        return
    code, _ = api("PATCH", f"/repos/{slug}/releases/{release['id']}", {"make_latest": "true"})
    say(f"latest 指向 {newest}" if code == 200 else f"latest 设置失败（HTTP {code}）")


def release_tags(slug: str) -> set[str]:
    status, data = api("GET", f"/repos/{slug}/releases?per_page=100")
    if status != 200 or not isinstance(data, list):
        return set()
    return {item.get("tag_name", "") for item in data}


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    with_asset = "--no-asset" not in argv
    replace = "--replace" in argv
    tags: list[str] = []
    for i, arg in enumerate(argv):
        if arg == "--tag" and i + 1 < len(argv):
            tags.append(argv[i + 1])
    slug = repo_slug()

    if "--all" in argv:
        existing = release_tags(slug)
        for path in sorted(DIST.glob("jiyi-app-*.zip")):
            version = path.stem.rsplit("-", 1)[-1]
            tag = f"v{version}"
            if tag not in existing:
                tags.append(tag)
        if not tags:
            say("所有有包的版本都已建 Release，无需操作")
            return 0

    if not tags:
        tags = [f"v{read_version()}"]

    say(f"仓库 {slug}，共 {len(tags)} 个版本，凭据来源："
        f"{'环境变量' if (os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')) else 'git 凭据管理器'}")
    failed: list[str] = []
    for tag in tags:
        if not publish(slug, tag, dry_run, with_asset, replace):
            failed.append(tag)
    if failed:
        say(f"失败的版本：{', '.join(failed)}")
        return 1
    if not dry_run:
        ensure_latest(slug, tags)
    say("全部完成" if not dry_run else "dry-run 结束，未产生任何改动")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # 控制台 cp936 下中文不乱码
        except (AttributeError, ValueError):
            pass
    raise SystemExit(main(sys.argv[1:]))
