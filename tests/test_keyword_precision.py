"""关键词直出的精度回归：否定作用域、极性冲突、解释型意图、单文档收敛、开关回退。

这些用例都来自实测翻车现场，不是构造出来的边角：
- 「我不爱吃香菜」曾同时返回「不吃的食物」和「爱吃的食物」，答案自相矛盾；
- 「我不喜欢的运动」曾把「运动：每周三次游泳」当成答案；
- 「今天天气怎么样」曾因问句里带「怎么」被当成可直出（现已交给检索）。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.chunking import load_corpus  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.keywords import KeywordIndex  # noqa: E402

DEMO = ROOT / "data" / "demo"


def index_for(path, **env) -> KeywordIndex:
    keys = ("KEYWORD_INDEX", *env)
    old = {k: os.environ.get(k) for k in keys}
    os.environ["KEYWORD_INDEX"] = os.path.join(tempfile.mkdtemp(prefix="kw_prec_"), "kw.json")
    os.environ.update({k: str(v) for k, v in env.items()})
    try:
        index = KeywordIndex(load_corpus(str(path)), load_settings())
        index.ensure(enrich=False)
        return index
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def terms(index: KeywordIndex, query: str) -> list[str]:
    return [h.entry.term for h in index.match_report(query).hits]


def test_negation_scope() -> None:
    index = index_for(DEMO)
    report = index.match_report("我不爱吃香菜")
    assert [h.entry.term for h in report.hits] == ["香菜"], terms(index, "我不爱吃香菜")
    assert "爱吃的食物" not in terms(index, "我不爱吃香菜"), "否定域内的「爱吃」不能当命中"
    assert {"term": "爱吃的食物", "reason": "negated"} in report.rejected, report.rejected
    assert all("爱吃的食物" not in h.entry.snippet for h in report.hits)

    # 同一句里一正一负，两处都该保留
    both = terms(index, "我爱吃火锅但我不爱吃香菜")
    assert "火锅" in both and "香菜" in both, both
    print("negation scope OK")


def test_polarity_conflict() -> None:
    index = index_for(DEMO)
    got = terms(index, "我不喜欢的运动是什么")
    assert got == ["不喜欢的运动"], got
    report = index.match_report("我不喜欢的运动是什么")
    assert {"term": "运动", "reason": "polarity_conflict"} in report.rejected, report.rejected

    # 正向问句保留中性条目，但不能带出「不喜欢的运动」
    assert terms(index, "我喜欢运动吗") == ["运动"], terms(index, "我喜欢运动吗")

    from src.keywords import _polarity
    assert _polarity("不喜欢的运动") == (-1, "运动")
    assert _polarity("爱吃的食物") == (1, "食物")
    assert _polarity("非常喜欢辣")[0] == 0, "「非常」不是否定"
    assert _polarity("起床时间") == (0, "起床时间")
    print("polarity conflict OK")


def test_explain_intent_gate() -> None:
    index = index_for(DEMO)
    for query in ("我为什么不能吃香菜", "我该怎么安排运动", "饮食和运动的区别是什么"):
        report = index.match_report(query)
        assert report.gate == "explain_intent", (query, report.gate)
        assert not report.hits, (query, terms(index, query))
    # 本来就没有命中候选时，不该记成「被意图挡下」，否则指标失真
    unrelated = index.match_report("今天天气怎么样")
    assert unrelated.gate is None and not unrelated.hits, unrelated.gate
    print("explain-intent gate OK")


def test_measure_noise_filtered() -> None:
    index = index_for(DEMO)
    assert "每次 1 小时" not in {e.term for e in index.entries}
    assert "每周三次游泳" in {e.term for e in index.entries}
    print("measure noise filter OK")


def test_single_doc_convergence() -> None:
    root = Path(tempfile.mkdtemp(prefix="kw_docs_"))
    (root / "a.md").write_text("# 甲的偏好\n\n## 一、饮品\n\n- 咖啡：拿铁、美式\n", encoding="utf-8")
    (root / "b.md").write_text("# 乙的偏好\n\n## 一、饮品\n\n- 咖啡：速溶、冷萃\n", encoding="utf-8")

    index = index_for(root)
    report = index.match_report("咖啡")
    docs = {h.entry.doc_id for h in report.hits}
    assert len(docs) == 1, docs
    assert any(r["reason"] == "other_doc" for r in report.rejected), report.rejected

    multi = index_for(root, KEYWORD_MULTI_DOC="on")
    assert len({h.entry.doc_id for h in multi.match_report("咖啡").hits}) == 2
    print("single-doc convergence OK")


def test_guard_switch() -> None:
    """关闭闸门要能回到旧行为，便于 A/B 与回滚。"""
    index = index_for(DEMO, KEYWORD_GUARD="off")
    got = terms(index, "我不爱吃香菜")
    assert "爱吃的食物" in got, got
    assert index.match_report("我为什么不能吃香菜").gate is None
    print("guard switch OK")


def test_core_alias_scope() -> None:
    """「喜欢的音乐」的核心词「音乐」可以答，但只在第一人称提问时成立。"""
    index = index_for(DEMO)
    assert terms(index, "我喜欢什么音乐") == ["喜欢的音乐"], terms(index, "我喜欢什么音乐")
    assert terms(index, "我讨厌什么天气") == ["讨厌的天气"], terms(index, "我讨厌什么天气")
    # 没有「我」的时候不能把文档主人的偏好当成通用知识
    assert not index.match_report("明天天气").hits, terms(index, "明天天气")
    assert not index.match_report("最近音乐节").hits, terms(index, "最近音乐节")
    print("core alias scope OK")


def test_index_matches_linear_scan() -> None:
    """倒排索引的结果必须与逐条包含判断一致，否则优化就成了引入 bug。"""
    from src.keywords import DIRECT_KINDS, _norm

    index = index_for(DEMO)
    queries = ["我爱吃什么", "我不吃什么", "我有什么忌口", "我养了什么宠物",
               "我几点起床", "我的早餐是什么", "我喜欢什么音乐"]
    for query in queries:
        q = _norm(query)
        expect = set()
        for entry in index.entries:
            if entry.kind not in DIRECT_KINDS:
                continue
            if any(len(k) >= 2 and k in q for k in entry.keys()):
                expect.add(entry.term)
        got = {h.entry.term for h in index.match_report(query).hits}
        assert expect == got, (query, sorted(expect - got), sorted(got - expect))
    print("inverted index consistency OK")


def test_citation_alignment() -> None:
    """答案里的 [n] 必须和 citations 一一对应，不能出现只有引用没有正文的编号。"""
    from src.keywords import KeywordIndex as KI
    index = index_for(DEMO)
    hits = KI.merge(index.match_report("我的爱好和宠物").hits)
    answer = KI.compose(hits)
    refs = [line.rsplit(" [", 1)[-1].rstrip("]") for line in answer.splitlines() if " [" in line]
    assert refs == [str(i) for i in range(1, len(hits) + 1)], (answer, len(hits))
    print("citation alignment OK")


def main() -> None:
    if not (DEMO / "小a的生活习惯.md").exists():
        raise SystemExit(f"缺少演示文档: {DEMO}")
    test_negation_scope()
    test_polarity_conflict()
    test_explain_intent_gate()
    test_measure_noise_filtered()
    test_single_doc_convergence()
    test_guard_switch()
    test_core_alias_scope()
    test_index_matches_linear_scan()
    test_citation_alignment()
    print("ALL KEYWORD PRECISION TESTS PASSED")


if __name__ == "__main__":
    main()
