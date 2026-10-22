"""版本硬链接与保留策略：未变更文件不重复占盘，旧版本按 N 保留。

硬链接不只是省磁盘：它保留原文件的 mtime，增量重建索引才能凭 mtime
认出「这份文档没变」。所以这里同时断言 inode 复用与内容正确。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kbstore import KnowledgeStore  # noqa: E402


def _seed(root: Path, n: int = 4) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (root / f"doc{i}.md").write_text(
            f"# 文档{i}\n\n## 要素\n\n原始内容 {i}。\n", encoding="utf-8")
    return root


def _approve(store: KnowledgeStore, name: str, text: str) -> dict:
    staged = store.stage({name: text}, author="tester", note="test")
    return store.approve(staged["change"]["change_id"], approver="tester")


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="kb_link_"))
    store = KnowledgeStore(str(tmp / "kb"), seed_dir=str(_seed(tmp / "seed")), keep_versions=3)
    store.bootstrap()
    first = store.active_version()

    for i in range(5):
        name = f"doc{i % 4}.md"
        res = _approve(store, name, f"# 文档{i % 4}\n\n## 要素\n\n修改后的内容 {i}。\n")
        assert res["manifest"]["linked_docs"] == 3, res["manifest"]
    print("硬链接计数 OK：每次 3 份未变更文档复用 inode")

    latest = store.active_version()
    versions = [v["version"] for v in store.versions()]
    assert len(versions) == 3, versions
    assert latest in versions and first not in versions, (versions, first)
    assert versions == sorted(versions), versions
    print(f"保留策略 OK：只留最近 3 版 {versions}，活动版本 {latest}")

    # 未变更文件与上一版共享 inode（Windows 的 st_ino 也是文件索引）
    prev = store.versions()[-2]["version"]
    same_name = "doc3.md"  # 5 次修改的是 doc0..doc0，doc3 只在第 4 次改过
    cur_path = Path(store.version_dir(latest)) / "files" / same_name
    prev_path = Path(store.version_dir(prev)) / "files" / same_name
    if cur_path.exists() and prev_path.exists():
        assert cur_path.stat().st_ino == prev_path.stat().st_ino, "未变更文件未复用 inode"
        assert cur_path.stat().st_nlink >= 2
        print(f"inode 复用 OK：{same_name} nlink={cur_path.stat().st_nlink}")

    # 内容仍然可读且是最新版本
    changed = Path(store.version_dir(latest)) / "files" / "doc0.md"
    assert "修改后的内容 4" in changed.read_text(encoding="utf-8")

    # ---------- 文件系统不支持硬链接时回退复制 ----------
    real_link = os.link

    def no_link(*args, **kwargs):
        raise OSError("hardlink unsupported")

    os.link = no_link
    try:
        res = _approve(store, "doc0.md", "# 文档0\n\n## 要素\n\n回退复制的内容。\n")
    finally:
        os.link = real_link
    assert res["manifest"]["linked_docs"] == 0, res["manifest"]
    copied = Path(store.version_dir(res["version"])) / "files" / "doc0.md"
    assert "回退复制的内容" in copied.read_text(encoding="utf-8")
    print("硬链接失败回退复制 OK")

    # ---------- 0 = 关闭清理 ----------
    tmp2 = Path(tempfile.mkdtemp(prefix="kb_keep_"))
    store2 = KnowledgeStore(str(tmp2 / "kb"), seed_dir=str(_seed(tmp2 / "seed")), keep_versions=0)
    store2.bootstrap()
    for i in range(4):
        res = _approve(store2, "doc0.md", f"# 文档0\n\n## 要素\n\n版本 {i}。\n")
        assert res["pruned"] == [], res
    assert len(store2.versions()) == 5, len(store2.versions())
    print("KB_KEEP_VERSIONS=0 不清理 OK：保留全部 5 版")

    print("KB HARDLINK TESTS PASSED")


if __name__ == "__main__":
    main()
