"""笔记检索的分词缓存：必须快，但绝不能快在「用旧内容打分」上。

守四条底线：
1. 缓存不改变结果——同一查询两次，分数与排序逐项相同；
2. 笔记改了必须立刻生效，不能因为缓存搜到旧词、搜不到新词;
3. 删掉的笔记不能留在缓存里（同 id 重建时不该复用旧词频）;
4. 缓存有上限，不会随着笔记数无限长到把内存吃满。

不联网：embedding 一律关闭，只测词面路径。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.notes import NoteService  # noqa: E402
from src.notes import search as search_mod  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def payload(title: str, body: str) -> dict:
    return {"messages": [{"role": "user", "text": body}],
            "hint": {"title": title, "kind": "note", "tags": []}}


def prepare(tmp: str) -> NoteService:
    os.environ["APP_CONFIG"] = str(Path(tmp) / "app.json")
    os.environ["EMBEDDING_PROVIDER"] = "none"
    service = NoteService(str(Path(tmp) / "store"))
    service.chat_call = None          # 摘要走规则引擎，不联网
    return service


def test_same_result(service: NoteService) -> None:
    print("两次同查询，结果必须逐项相同")
    service.save(payload("赎回规则", "赎回费按 0.5% 收取，持有满一年免收。"))
    first = service.search("赎回费")
    second = service.search("赎回费")
    check("首次能命中", bool(first["items"]), str(first["items"]))
    pairs_first = [(row["id"], row["score"]) for row in first["items"]]
    pairs_second = [(row["id"], row["score"]) for row in second["items"]]
    check("两次排序与分数完全一致", pairs_first == pairs_second,
          f"{pairs_first} vs {pairs_second}")
    check("缓存确实被用上了", len(service.searcher()._counts) >= 1,
          str(len(service.searcher()._counts)))


def test_edit_invalidates(service: NoteService) -> None:
    print("改了正文，旧词必须搜不到、新词必须搜得到")
    # keep_raw=False：默认会把原始消息留成「原文」节，那段也算检索文本，
    # 于是「改完还搜得到旧词」其实是对的。要测缓存失效必须先排除它。
    saved = service.save(payload("费用说明", "赎回费按 0.5% 收取。"), keep_raw=False)
    note_id = saved["id"]
    hit_before = [row["id"] for row in service.search("赎回费")["items"]]
    check("改之前能按旧词命中", note_id in hit_before, str(hit_before))

    # 空字符串表示删除该节：摘要与要点里都有原始消息，只改「摘要」等于旧词还在
    service.patch(note_id, {"sections": {"摘要": "申购费全免，另有管理费。", "要点": ""}},
                  force=True)
    hit_after = [row["id"] for row in service.search("赎回费")["items"]]
    check("改之后旧词不再命中", note_id not in hit_after, str(hit_after))
    new_hit = [row["id"] for row in service.search("申购费")["items"]]
    check("改之后新词能命中", note_id in new_hit, str(new_hit))


def test_delete_forgets(service: NoteService) -> None:
    print("删除笔记要把缓存一起清掉")
    saved = service.save(payload("待删除", "临时内容包括保证金比例。"))
    note_id = saved["id"]
    service.search("保证金")                      # 让这条进缓存
    searcher = service.searcher()
    check("删除前在缓存里", note_id in searcher._counts, str(list(searcher._counts)))
    service.delete(note_id)
    check("删除后不在缓存里", note_id not in searcher._counts,
          str(list(searcher._counts)))


def test_signature_fallback(tmp: str) -> None:
    """不经过 service（比如外部改了文件），也要靠签名发现变化。"""
    print("绕过 service 直接改文件，签名变化也要触发重算")
    home = Path(tmp) / "sig-store"
    searcher = search_mod.NoteSearcher(home, lambda entry: texts[entry["id"]])
    texts: dict[str, str] = {}
    note_path = home / "notes" / "x.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("第一版 托管费", encoding="utf-8")
    stat = note_path.stat()
    wanted = [{"id": "x", "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}]
    texts["x"] = "第一版 托管费"
    first = searcher.search("托管费", wanted, semantic="off")
    check("第一版能命中", "x" in first.scores, str(first.scores))

    note_path.write_text("第二版 销售服务费", encoding="utf-8")
    stat = note_path.stat()
    wanted = [{"id": "x", "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}]
    texts["x"] = "第二版 销售服务费"
    second = searcher.search("托管费", wanted, semantic="off")
    check("签名变了就不再命中旧词", "x" not in second.scores, str(second.scores))
    third = searcher.search("销售服务费", wanted, semantic="off")
    check("新内容能命中", "x" in third.scores, str(third.scores))


def test_cache_bound(service: NoteService) -> None:
    print("缓存有上限，超了要淘汰而不是无限涨")
    old = search_mod.COUNTS_CACHE_MAX
    search_mod.COUNTS_CACHE_MAX = 8        # 临时压低，避免真的写几千篇
    try:
        searcher = service.searcher()
        searcher._counts.clear()
        for index in range(40):
            service.save(payload(f"批量{index}", f"第 {index} 篇的内容 关键词{index}"))
            service.search(f"关键词{index}")
        size = len(searcher._counts)
        check("超过上限后被裁剪", size <= 8, f"实际 {size} 条")
        check("裁剪后仍能正常检索", bool(service.search("关键词39")["items"]))
    finally:
        search_mod.COUNTS_CACHE_MAX = old
        service.searcher()._counts.clear()


def test_speed(tmp: str) -> None:
    """用接近真实长度的笔记测：短文本一次分词只要几毫秒，看不出差别。"""
    print("热查询应显著快于冷查询")
    home = Path(tmp) / "speed-store"
    note_dir = home / "notes"
    note_dir.mkdir(parents=True, exist_ok=True)
    texts: dict[str, str] = {}
    wanted = []
    searcher = search_mod.NoteSearcher(home, lambda entry: texts[entry["id"]])
    for index in range(400):
        note_id = f"p{index:04d}"
        text = f"第{index}篇 理财说明 " + "稳盈系列产品的赎回费与期限条款说明 " * 60
        path = note_dir / f"{note_id}.md"
        path.write_text(text, encoding="utf-8")
        stat = path.stat()
        wanted.append({"id": note_id, "mtime_ns": stat.st_mtime_ns, "size": stat.st_size})
        texts[note_id] = text

    # 必须先建索引：单次查询只读 SYNC_MAX（默认 120）篇，
    # 不先重建的话两次查询读的是不同批次，缓存永远不命中，测出来的是假数据。
    searcher.rebuild(wanted, want_vec=False)

    started = time.monotonic()
    searcher.search("稳盈系列赎回费", wanted, semantic="off")
    cold = (time.monotonic() - started) * 1000
    started = time.monotonic()
    searcher.search("稳盈系列赎回费", wanted, semantic="off")
    hot = (time.monotonic() - started) * 1000
    print(f"     冷 {cold:.1f} ms / 热 {hot:.1f} ms（{len(wanted)} 篇）")
    check("热查询比冷查询快一倍以上", hot < cold * 0.5, f"冷 {cold:.1f} 热 {hot:.1f}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        service = prepare(tmp)
        test_same_result(service)
        test_edit_invalidates(service)
        test_delete_forgets(service)
        test_signature_fallback(tmp)
        test_speed(tmp)
        test_cache_bound(service)
    print()
    if FAILED:
        print(f"NOTES SEARCH CACHE FAILED: {FAILED}")
        return 1
    print("NOTES SEARCH CACHE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
