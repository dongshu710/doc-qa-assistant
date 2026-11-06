#!/usr/bin/env python3
"""Dify 外部知识库适配的单元测试。

只测适配层，不测检索质量——检索有自己的测试与评测集。这里盯的是四件事：
请求体校验（Dify 发的合法，别人发的不一定）、records 结构（Dify 只认它规定的字段）、
分数与阈值（量纲必须 0–1，否则阈值形同虚设）、top_k 是否真的透传到检索器
（不透传就是「对方设 5 条、这里按 4 条截断」，少的那条没有任何提示）。

直接跑：python tests/test_dify_retrieval.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import dify                                    # noqa: E402
from src.chunking import Chunk                          # noqa: E402
from src.pipeline import RAGPipeline                       # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def chunk(doc: str, section: str, text: str, index: int = 0) -> Chunk:
    return Chunk(doc_id=doc, title=doc, section=section, text=text, chunk_index=index)


class Recorder:
    """记录检索器被调用时拿到的 top_k：适配层最容易在这里悄悄吞掉参数。"""

    def __init__(self, hits):
        self.hits = hits
        self.calls: list[tuple] = []

    def search_ex(self, query, top_k=4, focus_query=None):
        self.calls.append((query, top_k, focus_query))
        return self.hits[:top_k], {"degraded": False, "error": None, "tokens": 0}


def fake_pipe(hits, configured_top_k: int = 4) -> RAGPipeline:
    """构造一个只装了 settings 与 retriever 的 Pipeline。

    用 `object.__new__` 绕开 __init__：真构造要知识库目录、要建索引，
    而这里要测的是 `_retrieve` 的参数透传，与索引无关。
    """
    pipe = object.__new__(RAGPipeline)
    pipe.settings = SimpleNamespace(top_k=configured_top_k)
    pipe.retriever = Recorder(hits)
    return pipe


def test_parse() -> None:
    print("请求体校验")
    ok = dify.parse_request({"query": "  起购金额是多少  ",
                             "retrieval_setting": {"top_k": 3, "score_threshold": 0.4}})
    check("正常请求解析", ok == ("起购金额是多少", 3, 0.4), str(ok))

    q, top_k, th = dify.parse_request({"query": "q"})
    check("缺 retrieval_setting 时用默认值", (top_k, th) == (dify.DEFAULT_TOP_K, 0.0),
          f"{top_k} / {th}")

    q, top_k, _ = dify.parse_request({"query": "q", "retrieval_setting": {"top_k": 999}})
    check("top_k 超上限被夹到 20", top_k == 20, str(top_k))

    check("空 query 不报错（Dify 探针就是空查询）", ok_empty(lambda: dify.parse_request({"query": ""})))
    check("缺 query 报错", _raises(lambda: dify.parse_request({})))
    check("query 非字符串报错", _raises(lambda: dify.parse_request({"query": 123})))
    check("非对象请求体报错", _raises(lambda: dify.parse_request([])))
    # bool 是 int 的子类：True 会被 int() 静默变成 1，不专门挡就查不出来
    check("top_k 传 true 报错",
          _raises(lambda: dify.parse_request({"query": "q", "retrieval_setting": {"top_k": True}})))
    check("top_k 传 0 报错",
          _raises(lambda: dify.parse_request({"query": "q", "retrieval_setting": {"top_k": 0}})))
    # 数字字符串是宽容接受的：不同平台序列化习惯不一样，能解析就用，
    # 解不出来才报错——「拒绝一种正确含义的写法」只会让对接方白折腾一轮。
    _, _, th = dify.parse_request({"query": "q", "retrieval_setting": {"score_threshold": "0.5"}})
    check("score_threshold 数字字符串被接受", th == 0.5, str(th))
    check("score_threshold 非数字字符串报错",
          _raises(lambda: dify.parse_request(
              {"query": "q", "retrieval_setting": {"score_threshold": "50%"}})))
    check("score_threshold 传 NaN 报错",
          _raises(lambda: dify.parse_request(
              {"query": "q", "retrieval_setting": {"score_threshold": float("nan")}})))


def _raises(fn) -> bool:
    try:
        fn()
    except dify.DifyError:
        return True
    except Exception:       # noqa: BLE001 —— 抛别的异常也算没过，但要看得到类型
        return False
    return False


def ok_empty(fn) -> bool:
    """解析成功且 query 为空：Dify 保存 API 连接时的探针请求就长这样。"""
    try:
        q, _top_k, _th = fn()
    except Exception:       # noqa: BLE001
        return False
    return q == ""


def test_records() -> None:
    print("records 结构")
    hits = [(chunk("01_产品说明.md", "起购金额", "起购金额为 1 万元。"), 0.87),
            (chunk("02_适当性.md", "风险等级", "R2 及以上客户可购买。"), 0.42)]
    out = dify.records(fake_pipe(hits), "起购金额", 4)
    check("条数正确", len(out) == 2, str(len(out)))
    first = out[0]
    check("content 首行是「文档 · 小节」", first["content"].startswith("01_产品说明.md · 起购金额"),
          first["content"][:30])
    check("content 含正文", "1 万元" in first["content"])
    check("title 是文档名", first["title"] == "01_产品说明.md", first["title"])
    check("metadata 是对象（不能是 null）", isinstance(first["metadata"], dict))
    check("metadata 带出处三件", set(first["metadata"]) == {"doc", "section", "chunk"},
          str(first["metadata"]))
    check("score 落在 0–1", all(0 <= r["score"] <= 1 for r in out))

    print("阈值与截断")
    filtered = dify.records(fake_pipe(hits), "起购金额", 4, threshold=0.5)
    check("阈值过滤掉低分", len(filtered) == 1, str(len(filtered)))
    check("阈值 0 表示不过滤", len(dify.records(fake_pipe(hits), "q", 4, threshold=0.0)) == 2)

    print("top_k 透传")
    pipe = fake_pipe(hits, configured_top_k=4)
    dify.records(pipe, "q", 7)
    check("请求的 top_k 真的传给了检索器（不是配置值 4）",
          pipe.retriever.calls[0][1] == 7, str(pipe.retriever.calls))
    pipe2 = fake_pipe(hits, configured_top_k=4)
    dify.records(pipe2, "q", 0)     # 非法值退回配置，而不是传 0 拿空结果
    check("top_k=0 退回配置值", pipe2.retriever.calls[0][1] == 4, str(pipe2.retriever.calls))


def test_edge() -> None:
    print("边界数据")
    check("空命中返回空 records", dify.records(fake_pipe([]), "q", 4) == [])

    # 探针请求不能真的去跑 embedding：既浪费，也会让「探针」变成一次真实检索
    probe = fake_pipe([(chunk("a.md", "", "正文"), 0.9)])
    check("空 query 返回空且不调检索器",
          dify.records(probe, "   ", 4) == [] and not probe.retriever.calls,
          str(probe.retriever.calls))

    # 分数越界（理论上不会，但检索器实现一变就可能）：宁可夹住，不能把 2.0 发给 Dify
    out = dify.records(fake_pipe([(chunk("a.md", "", "正文"), 2.0)]), "q", 4)
    check("超 1 的分数被夹到 1", out[0]["score"] == 1.0, str(out[0]["score"]))
    out = dify.records(fake_pipe([(chunk("a.md", "", "正文"), -0.3)]), "q", 4)
    check("负分被夹到 0", out[0]["score"] == 0.0, str(out[0]["score"]))

    # NaN 参与比较永远为假，会一路漏进排序；直接丢掉这一条
    out = dify.records(fake_pipe([(chunk("a.md", "", "正文"), float("nan")),
                                  (chunk("b.md", "", "正文"), 0.5)]), "q", 4)
    check("NaN 分数被丢弃", len(out) == 1 and out[0]["title"] == "b.md", str(out))

    # 没有小节时首行只留文档名，不留一个孤零零的「 · 」
    out = dify.records(fake_pipe([(chunk("a.md", "", "正文"), 0.5)]), "q", 4)
    check("无小节时首行无多余分隔符", out[0]["content"].startswith("a.md\n"), repr(out[0]["content"][:12]))


def main() -> int:
    print("DIFY RETRIEVAL")
    test_parse()
    test_records()
    test_edge()
    print("\nDIFY OK" if not FAILED else f"\n{FAILED} 项失败")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
