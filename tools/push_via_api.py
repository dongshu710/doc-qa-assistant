#!/usr/bin/env python3
"""`git push` 走不通时的兜底：用 Git Data API 把本地 HEAD 的树推到远端。

为什么需要：这台机器上 `github.com:443` 经常被代理掐断（schannel: server closed abruptly），
但 `api.github.com` 一直通。于是把「推代码」拆成几次 REST 调用：
上传变化的 blob → 建 tree → 建 commit → 移动 ref。树的内容与本地逐字节一致。

用法：
    python tools/push_via_api.py --dry-run        # 只看会改哪些文件
    python tools/push_via_api.py                  # 提交信息取本地 HEAD 的 subject
    python tools/push_via_api.py -m "全量提交信息"

SHA 一致性：建 commit 时会把本地 HEAD 的 author/committer（名字、邮箱、**带时区的 ISO 时间**）
一并传过去，所以父提交对得上时，远端 commit 与本地是**同一个对象**，SHA 相同，推完不需要 reset。

这里曾经写的是「GitHub 会把 `+08:00` 规范成 `Z`，哈希必然变」——错的。实测（v1.28.0）：
不传 author/committer 时 GitHub 用「认证账号 + 推送那一刻」补齐，时间戳和本地根本不是一回事，
SHA 当然不同；传了之后 SHA 逐字节一致。差别全在调用方，不在 GitHub 的时区处理。

SHA 确实不同的两种情况，脚本会直接说是哪一种：
  - 用了 `-m`：提交信息与本地 HEAD 不同，本来就不是同一个对象；
  - 本地 HEAD 的父提交不是远端当前提交（本地落后于远端，或历史分叉）。
第二种才是真正需要 `git fetch origin && git reset --hard origin/main` 的场景。
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


def head_identity() -> dict:
    """本地 HEAD 的作者/提交者身份，原样取名字、邮箱与带时区的时间。

    必须显式传：不传时 GitHub 用「认证账号 + 当前时刻」补齐，同一个 tree 也会得到
    另一个 SHA，本地与远端就长期「内容同步、SHA 分叉」，每次推完都得 reset。

    时间用 `%aI`（ISO 8601，保留 `+08:00` 偏移）。只传 `%at` 的 epoch 会丢掉时区，
    git 对象里 author 行的尾段不同，SHA 又对不上。字段用 \\x1f 分隔，避开姓名里可能出现的空格。
    """
    raw = git("log", "-1", "--format=%an%x1f%ae%x1f%aI%x1f%cn%x1f%ce%x1f%cI")
    name, mail, date, cname, cmail, cdate = raw.split("\x1f")
    return {
        "author": {"name": name, "email": mail, "date": date},
        "committer": {"name": cname, "email": cmail, "date": cdate},
    }


def head_message() -> str:
    """HEAD 提交信息原文，连尾部换行一起保留。

    `git log --format=%B` 出来的字串会被 git() 的 strip 削掉尾巴，拼出的 commit
    与本地少一个换行就换了 SHA。直接从 commit 对象里切，不经过任何规整。
    """
    raw = git("cat-file", "commit", "HEAD", binary=True).decode("utf-8", "replace")
    return raw.split("\n\n", 1)[1] if "\n\n" in raw else ""


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
    custom_message = "-m" in argv
    if custom_message:
        message = argv[argv.index("-m") + 1]
    if not message:
        message = head_message()

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

    # 身份必须跟着走：不带 author/committer，GitHub 会补成「认证账号 + 此刻」，
    # 同一个 tree 也会落成另一个 SHA（见文件头说明）。
    status, commit = api("POST", f"/repos/{repo}/git/commits",
                         {"message": message, "tree": tree["sha"], "parents": [remote_sha],
                          **head_identity()})
    if status != 201:
        die(f"建提交失败：{status} {commit}")

    status, updated = api("PATCH", f"/repos/{repo}/git/refs/heads/{BRANCH}",
                          {"sha": commit["sha"], "force": False})
    if status not in (200, 201):
        die(f"移动分支失败：{status} {updated}")

    local_head = git("rev-parse", "HEAD")
    parents = git("log", "-1", "--format=%P").split()
    say(f"已推送：本地 {local_head[:7]} → 远端 {commit['sha'][:7]}")

    # SHA 一致时不需要 reset：这一步以前被当成「必然不同」而每次都得做，
    # 但真正需要 reset 的只有「父提交不同」这一种，分开说清，别让用户白跑一条可能覆盖改动的命令。
    if commit["sha"] == local_head:
        say("远端与本地是同一个提交对象（SHA 一致），可以直接继续开发")
    elif custom_message:
        say("远端 SHA 与本地不同：本次用了 -m，提交信息与本地 HEAD 不一致，属预期")
    elif parents != [remote_sha]:
        say(f"远端 SHA 与本地不同：本地 HEAD 的父提交是 "
            f"{parents[0][:7] if parents else '（无，首个提交）'}，远端当前是 {remote_sha[:7]}，"
            f"说明本地落后于远端或历史已分叉。同步一次再继续：")
        say("  git fetch origin && git reset --hard origin/main")
    else:
        say("远端 SHA 与本地不同，但父提交与提交信息都一致——身份或时间戳没能原样传过去，"
            "请检查 head_identity() 取到的字段")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
