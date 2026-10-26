"""存储占用与清理：数字要对得上磁盘，清理不能动活动版本。

为什么单独测：
1. 面板上的「已用 89.9 MB」如果和资源管理器差一截，用户就不信这个页面；
2. 清理是唯一会删文件的按钮，删错版本等于把可回滚的历史抹掉。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import appconfig, kbstore, settings_ops  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"  <- {detail}" if detail else ""))


def write(path: Path, text: str = "x" * 100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_size_of() -> None:
    print("目录统计")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root / "a.md", "12345")
        write(root / "sub" / "b.md", "1234567890")
        stat = settings_ops._size_of(root)
        check("字节数是真实值", stat["bytes"] == 15, str(stat))
        check("文件数含子目录", stat["files"] == 2, str(stat))
        missing = settings_ops._size_of(root / "nope")
        check("目录不存在返回 0", missing == {"bytes": 0, "files": 0}, str(missing))
        single = settings_ops._size_of(root / "a.md")
        check("单文件也能统计", single == {"bytes": 5, "files": 1}, str(single))


def test_storage_report() -> None:
    print("占用报表")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        home = root / "agent-notes"
        write(home / "notes" / "2026" / "a.md", "a" * 300)
        write(home / "notes" / "2026" / "b.md", "b" * 200)
        write(home / "index" / "notes.jsonl", "i" * 50)
        kb = root / "kb"
        for name in ("v0001", "v0002"):
            write(kb / "versions" / name / "manifest.json", "{}")
        cfg = root / "app.json"
        write(cfg, "{}")
        report = settings_ops.storage_report(str(home), str(kb), str(root / "emb"),
                                             str(cfg), 30)
        check("笔记字节数", report["notes"]["bytes"] == 500, str(report["notes"]))
        check("笔记篇数", report["notes"]["files"] == 2, str(report["notes"]))
        check("索引单独统计", report["index"]["bytes"] == 50, str(report["index"]))
        check("知识库版本数", report["kb"]["versions"] == 2, str(report["kb"]))
        check("磁盘容量可读", report["disk"]["total"] > 0 and report["disk"]["free"] > 0,
              str(report["disk"]))
        check("保留版本回显", report["keep_versions"] == 30, str(report["keep_versions"]))
        check("路径是绝对路径", os.path.isabs(report["notes"]["path"]), report["notes"]["path"])


def test_storage_cache() -> None:
    """缓存不能给出过期数字，也不该把「没变」当成「变」。

    面板每点一次齿轮都会取一遍报表，笔记上千篇时这是一次全盘遍历；
    缓存要同时做到两件相反的事：命中时够快、目录一变就立刻作废。
    """
    print("统计缓存")
    settings_ops.invalidate_storage()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        home = root / "agent-notes"
        write(home / "notes" / "2026" / "a.md", "a" * 100)
        write(home / "index" / "notes.jsonl", "{}\n")
        args = (str(home), str(root / "kb"), "", "", 30)

        first = settings_ops.storage_report(*args)
        check("首次是实扫", first["cached"] is False, str(first["cached"]))
        second = settings_ops.storage_report(*args)
        check("第二次命中缓存", second["cached"] is True, str(second["cached"]))
        check("命中不花时间", second["took_ms"] == 0, str(second["took_ms"]))
        check("命中数字一致", first["notes"] == second["notes"], f"{first['notes']} vs {second['notes']}")
        check("命中率被记录", settings_ops.storage_stats()["hits"] >= 1)

        # 改返回的 dict 不能污染缓存（有人会往里面塞字段）
        second["notes"]["bytes"] = -1
        third = settings_ops.storage_report(*args)
        check("返回值是副本", third["notes"]["bytes"] == 100, str(third["notes"]))

        # 存一篇笔记 = 写文件 + 追加索引；索引 mtime 变，缓存必须立刻作废
        write(home / "notes" / "2026" / "b.md", "b" * 50)
        with open(home / "index" / "notes.jsonl", "a", encoding="utf-8") as handle:
            handle.write('{"id":"b"}\n')
        fresh = settings_ops.storage_report(*args)
        check("新增笔记后不再是缓存", fresh["cached"] is False, str(fresh["cached"]))
        check("新笔记被算进去", fresh["notes"]["files"] == 2 and fresh["notes"]["bytes"] == 150,
              str(fresh["notes"]))

        forced = settings_ops.storage_report(*args, fresh=True)
        check("fresh=True 一定重扫", forced["cached"] is False)
        settings_ops.invalidate_storage()
        after = settings_ops.storage_report(*args)
        check("显式作废后重扫", after["cached"] is False)

        # 报告里的篇数要能当「笔记总数」用（设置面板就是这么复用的）
        check("篇数与 count_notes 一致", settings_ops.count_notes(str(home)) == after["notes"]["files"],
              f"{settings_ops.count_notes(str(home))} vs {after['notes']['files']}")


def test_clear_index() -> None:
    print("清理索引缓存")
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "agent-notes"
        write(home / "index" / "notes.jsonl", "x" * 123)
        freed = settings_ops.clear_index(str(home))
        check("返回释放字节", freed == 123, str(freed))
        check("索引目录已删除", not (home / "index").exists())
        check("笔记目录不受影响", (home / "notes").exists() is False)  # 本用例没建笔记，验证没被误建


def test_prune_versions() -> None:
    print("版本清理")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "kb"
        for index in range(1, 6):
            write(root / "versions" / f"v{index:04d}" / "manifest.json", "{}")
        (root / "pending").mkdir(parents=True)
        (root / "changes").mkdir(parents=True)
        (root / "state.json").write_text(
            json.dumps({"active": "v0005", "next_version": 6, "next_change": 1}),
            encoding="utf-8")
        store = kbstore.KnowledgeStore(str(root), keep_versions=5)
        removed = store.prune_versions(2)
        left = sorted(os.listdir(root / "versions"))
        check("只保留最近 2 版", left == ["v0004", "v0005"], str(left))
        check("返回值列出被删版本", removed == ["v0001", "v0002", "v0003"], str(removed))
        check("活动版本永远保留", "v0005" in left)
        check("再次清理无变化", store.prune_versions(2) == [])
        check("保留数为 0 表示不清理", store.prune_versions(0) == [])


def test_keep_versions_config() -> None:
    print("保留版本的配置读写")
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "app.json"
        old = os.environ.get("APP_CONFIG")
        os.environ["APP_CONFIG"] = str(target)
        try:
            appconfig._cache = None
            appconfig._cache_stat = None
            check("默认 30", appconfig.keep_versions() == 30, str(appconfig.keep_versions()))
            appconfig.update({"storage": {"keep_versions": "10"}})
            check("写入后生效", appconfig.keep_versions() == 10, str(appconfig.keep_versions()))
            check("view 回显真实值", appconfig.view()["storage"]["keep_versions"] == 10)
            appconfig.update({"storage": {"keep_versions": "0"}})
            check("0 是合法值", appconfig.keep_versions() == 0, str(appconfig.keep_versions()))
            for bad in ("三十", "-1", "3.5"):
                try:
                    appconfig.update({"storage": {"keep_versions": bad}})
                    check(f"拒绝非法值 {bad}", False)
                except ValueError:
                    check(f"拒绝非法值 {bad}", True)
        finally:
            if old is None:
                os.environ.pop("APP_CONFIG", None)
            else:
                os.environ["APP_CONFIG"] = old
            appconfig._cache = None
            appconfig._cache_stat = None


def main() -> int:
    test_size_of()
    test_storage_report()
    test_storage_cache()
    test_clear_index()
    test_prune_versions()
    test_keep_versions_config()
    print(f"\n{PASS} 项通过，{FAIL} 项失败")
    if FAIL:
        return 1
    print("STORAGE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
