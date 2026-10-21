"""关键词直出演示：用一份「小a的生活习惯」文档，展示上传 → 整理 → 命中 → 本地输出。

跑法：
    python tools/keyword_demo.py
    python tools/keyword_demo.py --dir data/demo --show-entries

输出里会明确标出每次问答走的是哪条路径、是否调用过模型。接了 API 时，
建索引阶段会用一次模型调用补摘要与同义词，问答阶段命中仍然零调用。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.pipeline import RAGPipeline  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=os.path.join(ROOT, "data", "demo"))
    parser.add_argument("--show-entries", action="store_true", help="打印抽取到的全部条目")
    parser.add_argument("--questions", nargs="*", default=[
        "我爱吃什么", "我不吃什么", "我有什么忌口", "我几点起床",
        "我养了什么宠物", "我有什么爱好", "今天天气怎么样",
    ])
    args = parser.parse_args()

    # 演示不污染正式知识库的关键词缓存
    os.environ.setdefault("KEYWORD_INDEX", os.path.join(ROOT, "data", "index", "keywords.demo.json"))
    pipe = RAGPipeline(args.dir)
    detail = pipe.keyword_detail
    print("文档目录:", args.dir)
    print("关键词索引:", json.dumps(detail, ensure_ascii=False))
    print("模型整理:", "已启用" if detail.get("llm") else "未启用（未配置 API Key）")
    print()

    for doc_id in pipe.keywords.docs:
        print(f"[{doc_id}] 关键词：", "、".join(pipe.keywords.top_terms(doc_id, 12)))
    print()

    if args.show_entries:
        for entry in pipe.keywords.entries:
            print(f"  {entry.kind:8} {entry.term:12} aliases={entry.aliases} <- {entry.snippet[:50]}")
        print()

    hit = 0
    for question in args.questions:
        result = pipe.ask(question)
        local = result.get("path") == "keyword"
        hit += 1 if local else 0
        print(f"Q: {question}")
        print(f"   路径={'本地关键词' if local else '检索生成'} · 模式={result.get('mode')} · "
              f"调用API={'是' if result.get('api_called') else '否'} · {result.get('latency_ms')} ms")
        print("   " + result["answer"].replace("\n", "\n   "))
        if result.get("citations"):
            refs = "、".join(f"[{c['ref']}] {c['title']}·{c['section']}" for c in result["citations"])
            print("   出处:", refs)
        print()

    print(f"命中 {hit}/{len(args.questions)} 条；未命中的问题回退到检索生成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
