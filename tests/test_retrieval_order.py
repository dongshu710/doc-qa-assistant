"""检索顺序：先判域、再扩展。

扩展要花一次 LLM + 一次 embedding。域外问题若也走扩展，等于白付两次调用，
而且扩展词会把域外问题「拉近」，让闸门更容易误放行。这个测试守住顺序：
域外 0 次扩展，域内 1 次；扩展分数不升时保留原结果。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["KEYWORD_INDEX"] = os.path.join(tempfile.mkdtemp(), "kw.json")
os.environ["RETRIEVAL"] = "bm25"
os.environ["MIN_SCORE"] = "0.5"
os.environ["QUERY_EXPANSION"] = "llm"
for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY"):
    os.environ.pop(key, None)

from src import pipeline as pipeline_module      # noqa: E402
from src.pipeline import RAGPipeline             # noqa: E402


def main() -> None:
    calls: list[str] = []

    def fake_expand(query, vocabulary):
        calls.append(query)
        return query + " 起购 规则", True

    pipeline_module.expand = fake_expand
    pipe = RAGPipeline(str(ROOT / "data" / "knowledge"))

    # ---------- 1) 域外问题：闸门先挡，不花扩展 ----------
    before = len(calls)
    miss = pipe.ask("今天天气怎么样")
    assert miss["behavior"] == "no_answer", miss["behavior"]
    assert miss["answer"] == "无法找到答案。", miss["answer"]
    assert len(calls) - before == 0, "域外问题不应触发查询扩展"
    assert miss["api_called"] is False, miss
    assert miss["min_score"] == 0.5 and miss["gate_score"] < 0.5, miss
    print(f"out-of-domain OK：gate={miss['gate_score']:.3f} < {miss['min_score']}，扩展 0 次")

    # ---------- 2) 域内问题：判域通过后才扩展 ----------
    before = len(calls)
    hit = pipe.ask("稳盈系列的起购金额是多少")
    assert hit["behavior"] == "answer", hit["behavior"]
    assert len(calls) - before == 1, "域内问题应扩展一次"
    assert hit["search_query"], hit
    assert hit["api_called"] is True, hit
    assert hit["retrieval_score"] >= hit["gate_score"], hit
    print(f"in-domain OK：gate={hit['gate_score']:.3f}，扩展 1 次，search_query={hit['search_query']!r}")

    # ---------- 3) 扩展结果更差时保留原检索 ----------
    pipeline_module.expand = lambda q, v: (q + " 完全无关的扩展词", True)
    worse = pipe.ask("大额存单可以转让吗")
    assert worse["behavior"] == "answer", worse["behavior"]
    assert worse["retrieval_score"] == worse["gate_score"], (
        "扩展后分数更低时应保留原问题的检索结果", worse["retrieval_score"], worse["gate_score"])
    print("expansion-never-worse OK")

    # ---------- 4) 扩展抛异常不影响主流程 ----------
    def boom(query, vocabulary):
        raise RuntimeError("扩展开关炸了")

    pipeline_module.expand = boom
    survived = pipe.ask("大额存单可以转让吗")
    assert survived["behavior"] == "answer", survived
    print("expansion-error tolerated OK")

    print("RETRIEVAL ORDER OK")


if __name__ == "__main__":
    main()
