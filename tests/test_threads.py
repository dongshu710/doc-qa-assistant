"""会话存储：落盘、列表、导入、越界与坏文件。

为什么单测：会话从 localStorage 搬到磁盘，是「数据会不会丢」级别改动。
这里每条断言都对应一个真实故障：路径越界会写坏别的目录、坏文件会让侧栏整块消失、
导入覆盖会让用户刚写的记录被浏览器旧数据顶掉。
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

from src import settings_ops  # noqa: E402
from src.threadstore import ThreadError, ThreadStore  # noqa: E402

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


def turn(q: str, answer: str = "答") -> dict:
    return {"q": q, "ts": "2026-10-26T20:00:00", "d": {"behavior": "answer", "answer": answer}}


def test_crud() -> None:
    print("增删改查")
    with tempfile.TemporaryDirectory() as tmp:
        store = ThreadStore(tmp)
        meta = store.put("tabc123456", {"title": "大额存单", "sid": "s1", "turns": [turn("问题一")]})
        check("写入返回元数据", meta["title"] == "大额存单" and meta["turns"] == 1, str(meta))
        path = Path(tmp) / "threads" / "tabc123456.json"
        check("落成一个文件", path.is_file(), str(path))
        raw = path.read_text(encoding="utf-8")
        check("是可读 JSON（人能改）", json.loads(raw)["schema"] == "thread/v1")
        check("换行是 LF", "\r\n" not in raw)

        got = store.get("tabc123456")
        check("读回正文", got["turns"][0]["q"] == "问题一" and got["title"] == "大额存单", str(got)[:120])

        listed = store.list()
        check("列表带篇数但不带正文", listed[0]["turns"] == 1 and "turns" not in str(listed[0].get("x")),
              str(listed)[:100])

        store.put("tabc123456", {"title": "改过的标题", "turns": [turn("问题一"), turn("问题二")]})
        check("整条覆盖写", store.get("tabc123456")["title"] == "改过的标题")
        check("轮数跟着变", len(store.get("tabc123456")["turns"]) == 2)

        store.delete("tabc123456")
        check("删除后文件消失", not path.exists())
        try:
            store.get("tabc123456")
            check("读不存在的会话报 KeyError", False)
        except KeyError:
            check("读不存在的会话报 KeyError", True)


def test_guards() -> None:
    print("参数与路径")
    with tempfile.TemporaryDirectory() as tmp:
        store = ThreadStore(tmp)
        for bad in ("", "abc", "../../etc/passwd", "a" * 41, "有中文的id"):
            try:
                store.path_for(bad)
                check(f"拒绝非法 id：{bad[:14]}", False)
            except ThreadError:
                check(f"拒绝非法 id：{bad[:14]}", True)
        check("id 全部落在 threads 目录", store.path_for("tabcdef123").parent == store.dir)
        try:
            store.put("tabcdef123", {"turns": "不是数组"})
            check("turns 必须是数组", False)
        except ThreadError:
            check("turns 必须是数组", True)
        try:
            store.put("tabcdef123", {"turns": [turn(f"q{i}") for i in range(501)]})
            check("超长会话被拒（提示存成笔记）", False)
        except ThreadError as exc:
            check("超长会话被拒（提示存成笔记）", "500" in str(exc), str(exc))


def test_corrupt_and_import() -> None:
    print("坏文件与导入")
    with tempfile.TemporaryDirectory() as tmp:
        store = ThreadStore(tmp)
        broken = Path(tmp) / "threads" / "tbroken1234.json"
        broken.write_text("{不是 JSON", encoding="utf-8")
        try:
            store.get("tbroken1234")
            check("坏文件给出可读错误", False)
        except ThreadError as exc:
            check("坏文件给出可读错误", "JSON" in str(exc), str(exc))
        check("坏文件不影响列表", all(item["id"] != "tbroken1234" for item in store.list()))

        copied = store.import_many([
            {"id": "tlegacy0001", "title": "旧的", "turns": [turn("老问题")]},
            {"id": "tbroken1234", "title": "不该覆盖", "turns": []},
            {"id": "bad id", "title": "非法", "turns": []},
        ])
        check("只导入合法且不存在的", copied == 1, str(copied))
        check("已存在的文件不被覆盖", "不" in broken.read_text(encoding="utf-8"))
        check("导入的能读出来", store.get("tlegacy0001")["title"] == "旧的")


def test_search_text() -> None:
    """索引里的搜索文本：侧栏搜索能不能搜到正文，全靠它。

    为什么要有这条：`list()` 只返回元数据、不含正文，侧栏搜索如果只比标题，
    「我记得问过起购金额」这种回忆就永远搜不到——标题是自动截的前 28 字。
    而把搜索做成「翻文件」又会让每次按键都读几百个 JSON。
    """
    print("索引里的搜索文本")
    with tempfile.TemporaryDirectory() as tmp:
        store = ThreadStore(tmp)
        store.put("tabc123456", {
            "title": "理财",
            "turns": [turn("理财产品的起购金额是多少", "这类产品一万元起购，追加一千元起")],
        })
        items = store.list(10)
        check("条目带 text 字段", "text" in items[0], str(sorted(items[0])))
        text = items[0].get("text") or ""
        check("问句进了 text", "起购金额" in text, text)
        # 答案只取开头一段：整段塞进索引会把几百条会话的索引撑到几 MB
        check("答案开头也进了 text", "一万元起购" in text, text)

        # 答案很长时只留开头 60 字，且整条 text 不超过上限
        store.put("tlong12345", {
            "title": "长答案",
            "turns": [turn("长问题" * 50, "长答案" * 200)],
        })
        long_text = store.list(10)[0].get("text") or ""
        check("text 有长度上限", len(long_text) <= 600, str(len(long_text)))
        check("长答案只留开头", long_text.count("长答案") <= 60, str(long_text.count("长答案")))


def test_index_schema_upgrade() -> None:
    """旧格式索引要被丢弃并重建，而不是带着缺字段的条目继续用。

    加字段时最容易漏的就是这里：`count` 没变，`_index()` 认为索引还是好的，
    于是搜索永远搜不到新字段——**不报错、只是结果少了**，比慢一次难发现得多。
    """
    print("索引格式升级")
    with tempfile.TemporaryDirectory() as tmp:
        store = ThreadStore(tmp)
        store.put("tabc123456", {"title": "旧索引", "turns": [turn("会被搜到的问句")]})
        # 索引是 `list()`/`_index()` 懒建的：`put` 只在索引已存在时顺手更新，
        # 不存在就直接返回（不为了写一条元数据去全扫一遍目录）。
        store.list(10)
        index_path = Path(tmp) / "threads" / "_index.json"
        raw = json.loads(index_path.read_text(encoding="utf-8"))

        # 伪造成旧版本：把 text 抹掉、版本号退回去，count 保持不变
        for entry in raw["items"].values():
            entry.pop("text", None)
        raw["schema"] = "thread-index/v1"
        index_path.write_text(json.dumps(raw), encoding="utf-8")

        items = store.list(10)
        check("旧索引被重建", items[0].get("text") == "会被搜到的问句" or "会被搜到" in (items[0].get("text") or ""),
              str(items[0].get("text")))
        fresh = json.loads(index_path.read_text(encoding="utf-8"))
        check("版本号已升级", fresh.get("schema") == "thread-index/v2", str(fresh.get("schema")))


def test_storage_report_counts_threads() -> None:
    print("存储统计包含会话")
    with tempfile.TemporaryDirectory() as tmp:
        store = ThreadStore(tmp)
        store.put("tabc123456", {"title": "会话", "turns": [turn("问题")]})
        settings_ops.invalidate_storage()
        report = settings_ops.storage_report(notes_home=tmp, kb_root="", index_dir="",
                                             config_path="", keep_versions=30)
        check("会话字节数 > 0", report["threads"]["bytes"] > 0, str(report["threads"]))
        check("会话条数 = 1", report["threads"]["files"] == 1, str(report["threads"]))
        check("文档与会话分开统计", report["notes"]["bytes"] == 0, str(report["notes"]))


def main() -> int:
    test_crud()
    test_guards()
    test_corrupt_and_import()
    test_search_text()
    test_index_schema_upgrade()
    test_storage_report_counts_threads()
    print(f"\n{PASS} 项通过，{FAIL} 项失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
