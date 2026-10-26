#!/usr/bin/env python3
"""`git push` 走不通时的兜底：用 Git Data API 把本地 HEAD 的树推到远端。

为什么需要：这台机器上 `github.com:443` 经常被代理掐断（schannel: server closed abruptly），
但 `api.github.com` 一直通。于是把「推代码」拆成几次 REST 调用：
上传变化的 blob → 建 tree → 建 commit → 移动 ref。树的内容与本地逐字节一致。

用法：
    python tools/push_via_api.py --dry-run        # 只看会改哪些文件
    python tools/push_via_api.py                  # 提交信息取本地 HEAD 的 subject
    python tools/push_via_api.py -m "全量提交信息"

副作用（必须知道）：远端 commit 的 SHA 和本地不一样——GitHub 会把 `+08:00` 规范成 `Z`，
父提交、时间戳都要重新拼，哈希必然变。所以推完之后要：
    git fetch origin && git reset --hard origin/main
否则本地继续提交再 push 会被判成「历史分叉」。
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.publish_release import api, die, repo_slug, say, token  # noqa: E402

BRANCH = "main"


def git(*args: str, binary: bool = False):
    proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    if proc.returncode != 0:
        die(f"git {' '.join(args)} 失败：{proc.stderr.decode('utf-8', 'replace')[:300]}")
    return proc.stdout if binary else proc.stdout.decode("utf-8", "replace").strip()


def local_entries() -> dict:
    """本地 HEAD 的全部文件：path -> (mode, blob sha)。"""
    raw = git("ls-tree", "-r", "-z", "HEAD", binary=True).decode("utf-8", "replace")
    entries = {}
    for item in raw.split("\0"):
        if not item:
            continue
        meta, path = item.split("\t", 1)
        mode, kind, sha = meta.split()
        if kind == "blob":
            entries[path] = (mode, sha)
    return entries


def remote_state(repo: str) -> tuple:
    status, ref = api("GET", f"/repos/{repo}/git/ref/heads/{BRANCH}")
    if status != 200:
        die(f"读不到远端 {BRANCH}：{status} {ref}")
    commit_sha = ref["object"]["sha"]
    status, commit = api("GET", f"/repos/{repo}/git/commits/{commit_sha}")
    if status != 200:
        die(f"读不到远端提交：{status} {commit}")
    tree_sha = commit["tree"]["sha"]
    status, tree = api("GET", f"/repos/{repo}/git/trees/{tree_sha}?recursive=1")
    if status != 200:
        die(f"读不到远端树：{status} {tree}")
    entries = {item["path"]: (item["mode"], item["sha"], item["type"])
               for item in tree.get("tree", [])}
    return commit_sha, tree_sha, entries


def main(argv: list) -> int:
    dry = "--dry-run" in argv
    message = ""
    if "-m" in argv:
        message = argv[argv.index("-m") + 1]
    if not message:
        message = git("log", "-1", "--pretty=%B")

    token()  # 先确认有令牌，别等传完 blob 才发现没权限
    repo = repo_slug()
    say(f"仓库 {repo} · 远端分支 {BRANCH}")

    local = local_entries()
    remote_sha, remote_tree, remote = remote_state(repo)
    say(f"本地 {len(local)} 个文件 · 远端 {len(remote)} 项（commit {remote_sha[:7]}）")

    uploads, deletes = [], []
    for path, (mode, sha) in sorted(local.items()):
        remote_item = remote.get(path)
        # remote_item = (mode, sha, type)；目录条目不算改动，只比 blob
        if not remote_item or remote_item[2] != "blob" or remote_item[1] != sha:
            uploads.append((path, mode, sha))
    for path, item in remote.items():
        # 目录不用显式删：子文件删空了目录自然消失
        if item[2] == "blob" and path not in local:
            deletes.append(path)

    say(f"需要上传 {len(uploads)} 个 · 删除 {len(deletes)} 个")
    for path, *_ in uploads[:40]:
        say(f"  + {path}")
    if len(uploads) > 40:
        say(f"  … 还有 {len(uploads) - 40} 个")
    for path in deletes[:20]:
        say(f"  - {path}")

    if not uploads and not deletes:
        say("远端已与本地一致，无需提交")
        return 0
    if dry:
        say("（--dry-run，未写入）")
        return 0

    tree_entries = []
    for path, mode, sha in uploads:
        blob = git("cat-file", "blob", sha, binary=True)
        status, created = api("POST", f"/repos/{repo}/git/blobs",
                              {"content": base64.b64encode(blob).decode("ascii"),
                               "encoding": "base64"})
        if status != 201:
            die(f"上传 {path} 失败：{status} {created}")
        tree_entries.append({"path": path, "mode": mode, "type": "blob", "sha": created["sha"]})
    for path in deletes:
        tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})

    status, tree = api("POST", f"/repos/{repo}/git/trees",
                       {"base_tree": remote_tree, "tree": tree_entries})
    if status != 201:
        die(f"建树失败：{status} {tree}")

    status, commit = api("POST", f"/repos/{repo}/git/commits",
                         {"message": message, "tree": tree["sha"], "parents": [remote_sha]})
    if status != 201:
        die(f"建提交失败：{status} {commit}")

    status, updated = api("PATCH", f"/repos/{repo}/git/refs/heads/{BRANCH}",
                          {"sha": commit["sha"], "force": False})
    if status not in (200, 201):
        die(f"移动分支失败：{status} {updated}")

    say(f"已推送：本地 {git('rev-parse', '--short', 'HEAD')} → 远端 {commit['sha'][:7]}")
    say("本地与远端 SHA 不同（GitHub 规范了时区），继续开发前执行：")
    say("  git fetch origin && git reset --hard origin/main")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
