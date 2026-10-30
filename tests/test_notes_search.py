"""笔记检索：词面 BM25 + 语义融合 + 降级。

守四条底线：
1. 没配 embedding 时仍能按字面找到，并且**如实自报**为 `lexical`；
2. 配了之后「换个说法」也能捞到——这是语义检索的全部意义；
3. embedding 挂了要降级、要留原因，不能静默变慢或返回空白；
4. 索引是派生的：第二次查询不重复算，文件改了必须重算。

不联网：embedding 用注入的假通道（按主题分桶的 4 维向量），
既能验证融合逻辑，又不会因为测试机没配模型而变成「只测了词面」。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.notes import NoteService  # noqa: E402
from src.notes import api as notes_api  # noqa: E402
from src.notes import search as search_mod  # noqa: E402
from src.notes.tools import TOOLS  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


# 主题桶：同桶里的词在假向量里方向相同，模拟「意思相近但用词不同」
BUCKETS = [
    ("部署", "上线", "发版", "deploy", "release"),
    ("税务", "退税", "发票"),
    ("预算", "经费", "成本"),
    ("招聘", "面试", "简历"),
]

DOCS = [
    ("部署方案确认", ["上线"], "decision", "灰度分两批，第一批 10%，观察 24 小时再放量。"),
    ("税务申报口径", ["税务"], "reference", "退税率按 13% 执行，每月 5 日前复核。"),
    ("季度预算复盘", ["预算"], "log", "差旅超支 12%，下季度压到 5% 以内。"),
]


def fake_embed(texts: list[str]) -> list[list[float]]:
    out = []
    for text in texts:
        vec = [0.0] * len(BUCKETS)
        for index, keys in enumerate(BUCKETS):
            if any(key in text for key in keys):
                vec[index] = 1.0
        if not any(vec):
            vec[-1] = 0.01      # 全零向量没有方向，给个极小值避免归一化后全是 0
        out.append(vec)
    return out


def payload(title: str, tags: list[str], kind: str, body: str) -> dict:
    return {"messages": [{"role": "user", "text": body}],
            "hint": {"title": title, "kind": kind, "tags": tags}}


def prepare(tmp: str) -> NoteService:
    # 界面配置优先于环境变量：指到一个不存在的文件，避免读到开发机上的真实模型配置
    os.environ["APP_CONFIG"] = str(Path(tmp) / "app.json")
    os.environ["EMBEDDING_PROVIDER"] = "none"
    service = NoteService(str(Path(tmp) / "store"))
    service.chat_call = None          # 摘要走规则引擎，不联网
    return service


def seed(service: NoteService) -> dict[str, str]:
    ids = {}
    for title, tags, kind, body in DOCS:
        result = service.save(payload(title, tags, kind, body))
        ids[title] = result["id"]
    return ids


def test_lexical_only(service: NoteService) -> None:
    print("没有 embedding 时只跑词面，并且如实自报")
    result = service.search("灰度")
    titles = [row["title"] for row in result["items"]]
    check("字面命中部署那篇", "部署方案确认" in titles, str(titles))
    check("自报模式为 lexical", result["search"]["mode"] == "lexical", str(result["search"]))
    check("没有降级原因（本来就没开语义）", result["search"]["degraded"] == "",
          str(result["search"]))
    check("结果带 score", all("score" in row for row in result["items"]),
          str(result["items"][:1]))
    check("没配 provider 时不该报「待索引」", result["search"]["pending"] == 0,
          str(result["search"]))

    miss = service.search("发版流程")
    check("词面搜不到换个说法的内容", not miss["items"], str([r["title"] for r in miss["items"]]))


def test_semantic_fusion(service: NoteService, calls: list) -> None:
    print("注入 embedding 后能按意思找到")
    service.embed_call = lambda texts: (calls.append(len(texts)), fake_embed(texts))[1]
    # 「发版」与文档里的「部署 / 上线」没有共同字符，词面一定搜不到，只能靠语义
    result = service.search("发版前要准备什么")
    titles = [row["title"] for row in result["items"]]
    check("换个说法也能命中部署那篇", "部署方案确认" in titles, str(titles))
    check("自报模式为 hybrid", result["search"]["mode"] == "hybrid", str(result["search"]))
    top = result["items"][0] if result["items"] else {}
    check("置顶项带语义分", top.get("title") == "部署方案确认", str(top.get("title")))


def test_semantic_off(service: NoteService, calls: list) -> None:
    print("semantic=off 不碰 embedding")
    calls.clear()
    result = service.search("发版前要准备什么", semantic="off")
    check("关闭后不调用 embedding", not calls, str(calls))
    check("关闭后模式是 lexical", result["search"]["mode"] == "lexical", str(result["search"]))
    check("关闭后搜不到换个说法的内容", not result["items"],
          str([r["title"] for r in result["items"]]))


def test_cache(service: NoteService, calls: list) -> None:
    print("索引命中后不重复算")
    service.rebuild_search()          # 先把索引补齐，让下面的断言只测「查询时做了什么」
    calls.clear()
    service.search("灰度")
    first = list(calls)
    calls.clear()
    service.search("灰度")
    second = list(calls)
    check("索引完整时只算查询向量", first == [1], str(first))
    check("第二次同样只算查询向量", second == [1], str(second))


def test_index_invalidation(service: NoteService, ids: dict, calls: list) -> None:
    print("文件改了要重算")
    calls.clear()
    service.patch(ids["税务申报口径"], {"title": "税务申报口径（更新）"}, force=True)
    result = service.search("退税")
    check("改标题后仍能搜到", any("税务" in row["title"] for row in result["items"]),
          str([r["title"] for r in result["items"]]))
    check("确实重新算了文档向量", sum(calls) >= 2, str(calls))


def test_filters_first(service: NoteService) -> None:
    print("先按条件筛，再按相关度排")
    service.embed_call = fake_embed
    hit = service.search("上线", tags=["税务"])
    check("标签不符的笔记不出现", all(row["title"] != "部署方案确认" for row in hit["items"]),
          str([r["title"] for r in hit["items"]]))
    empty = service.search("上线", kind="log")
    check("类型不符时为空", all(row["kind"] == "log" for row in empty["items"]),
          str([r["kind"] for r in empty["items"]]))


def test_embed_failure(service: NoteService) -> None:
    print("embedding 失败要降级并留原因")
    def broken(texts):
        raise RuntimeError("模型服务 502")
    service.embed_call = broken
    result = service.search("灰度")
    titles = [row["title"] for row in result["items"]]
    check("仍然返回词面结果", "部署方案确认" in titles, str(titles))
    check("留下降级原因", "embedding_failed" in result["search"]["degraded"],
          str(result["search"]))
    service.embed_call = None


def test_rebuild(service: NoteService) -> None:
    print("全量重建")
    service.embed_call = fake_embed
    result = service.rebuild_search()
    check("重建条数等于笔记数", result["notes"] == len(DOCS), str(result))
    index_file = service.store.home / "index" / search_mod.SEARCH_FILE
    check("索引文件已落盘", index_file.is_file(), str(index_file))
    rows = [json.loads(line) for line in index_file.read_text(encoding="utf-8").splitlines() if line]
    check("每条都带文本", all(row.get("text") for row in rows), str(len(rows)))
    check("每条都带向量", all(row.get("vec") for row in rows), str(len(rows)))


def test_http_api(service: NoteService) -> None:
    print("HTTP 契约")
    code, body, _ = notes_api.dispatch(service, "GET", "/api/notes",
                                      {"q": ["上线前要准备什么"], "limit": ["5"]}, None)
    check("200", code == 200, str(code))
    check("带 search 元信息", isinstance(body.get("search"), dict), str(body.get("search")))
    check("有结果", body.get("count", 0) >= 1, str(body.get("count")))
    check("没传 q 时是筛选模式", notes_api.dispatch(
        service, "GET", "/api/notes", {"limit": ["5"]}, None)[1]["search"]["mode"] == "filter")

    code, body, _ = notes_api.dispatch(service, "GET", "/api/notes",
                                       {"q": ["灰度"], "semantic": ["off"]}, None)
    check("semantic=off 被接受", code == 200 and body["search"]["mode"] == "lexical",
          str(body.get("search")))

    code, _, _ = notes_api.dispatch(service, "POST", "/api/notes/rebuild",
                                    {}, {"semantic": "auto"})
    check("rebuild 端点可用", code == 200, str(code))


def test_tool_schema() -> None:
    print("工具声明")
    tool = next(item for item in TOOLS if item["function"]["name"] == "search_notes")
    props = tool["function"]["parameters"]["properties"]
    check("声明了 query", "query" in props, str(list(props)))
    check("声明了 semantic", props.get("semantic", {}).get("enum") == ["auto", "off"],
          str(props.get("semantic")))


def test_tokenizer() -> None:
    print("分词")
    tokens = search_mod.tokenize("退税率 13% 按 Export 执行")
    check("中文切 2-gram", "退税" in tokens and "税率" in tokens, str(tokens[:8]))
    check("英文按词", "export" in tokens, str(tokens))
    check("空串不炸", search_mod.tokenize("") == [])


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        service = prepare(tmp)
        ids = seed(service)
        calls: list[int] = []

        test_tokenizer()
        test_lexical_only(service)
        test_semantic_fusion(service, calls)
        test_semantic_off(service, calls)
        test_cache(service, calls)
        test_index_invalidation(service, ids, calls)
        test_filters_first(service)
        test_embed_failure(service)
        test_rebuild(service)
        test_http_api(service)
        test_tool_schema()

    print(f"\n{'全部通过' if FAILED == 0 else f'{FAILED} 项失败'}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
