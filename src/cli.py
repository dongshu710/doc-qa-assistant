"""命令行入口：
  python -m src.cli "稳盈系列的起购金额是多少"   # 单次问答
  python -m src.cli                              # 交互模式

端点与模型走环境变量：LLM_BASE_URL / LLM_MODEL / LLM_API_KEY；
未配置 Key 时自动降级为离线抽取模式。
"""
import argparse
import json
import os

from .pipeline import RAGPipeline


def _knowledge_dir() -> str:
    """优先使用版本库的活动版本，未初始化时回退种子目录。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    state_path = os.path.join(root, "data", "kb", "state.json")
    if os.path.exists(state_path):
        try:
            with open(state_path, encoding="utf-8") as f:
                active = json.load(f).get("active")
            path = os.path.join(root, "data", "kb", "versions", str(active), "files")
            if active and os.path.isdir(path):
                return path
        except (OSError, json.JSONDecodeError):
            pass
    return os.path.join(root, "data", "knowledge")


def main() -> None:
    ap = argparse.ArgumentParser(description="记忆文档 · 文档问答")
    ap.add_argument("query", nargs="*", help="问题；省略则进入交互模式")
    ap.add_argument("--model", help="临时指定模型（等价于设置 LLM_MODEL）")
    ap.add_argument("--base-url", help="临时指定端点（等价于设置 LLM_BASE_URL）")
    args = ap.parse_args()

    if args.model:
        os.environ["LLM_MODEL"] = args.model
    if args.base_url:
        os.environ["LLM_BASE_URL"] = args.base_url

    pipe = RAGPipeline(_knowledge_dir())
    mode = "llm" if pipe.llm_ready else "extractive"
    print(f"[model={pipe.settings.model} base={pipe.settings.api_base} mode={mode}]", file=os.sys.stderr)

    if args.query:
        print(json.dumps(pipe.ask(" ".join(args.query)), ensure_ascii=False, indent=2))
        return

    if not os.isatty(0):
        print("非交互环境：请用命令行参数传入问题，例如 python -m src.cli \"问题\"")
        return

    print("记忆文档 · 文档问答（输入 exit 退出）")
    while True:
        try:
            query = input("\n问> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if query in ("exit", "quit"):
            break
        r = pipe.ask(query)
        print(r["answer"])
        if r["citations"]:
            refs = "; ".join(f"[{c['ref']}]《{c['title']}》·{c['section']}" for c in r["citations"])
            print(f"来源: {refs}")
        print(f"(behavior={r['behavior']}, mode={r['mode']}, degraded={r['degraded']}, {r['latency_ms']}ms)")


if __name__ == "__main__":
    main()
