"""命令行入口：
  python -m src.cli --list-channels
  python -m src.cli "稳盈系列的起购金额是多少"            # 默认通道 deepseek
  python -m src.cli --channel glm "R3 及以上产品首次购买有什么要求"  # 测试通道
  python -m src.cli                                        # 交互模式
"""
import argparse
import json
import os

from .config import CHANNELS, active_channel
from .pipeline import RAGPipeline


def _knowledge_dir() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data", "knowledge")


def main() -> None:
    ap = argparse.ArgumentParser(description="金融产品问答助手")
    ap.add_argument("query", nargs="*", help="问题；省略则进入交互模式")
    ap.add_argument("--channel", choices=list(CHANNELS), help="选择通道：deepseek(默认) / glm(测试)")
    ap.add_argument("--list-channels", action="store_true", help="列出通道并退出")
    args = ap.parse_args()

    if args.list_channels:
        current = active_channel()
        for name, label, base, model in [(n, c["label"], c["base_url"], c["model"]) for n, c in CHANNELS.items()]:
            mark = "*" if name == current else " "
            print(f"{mark} {name:8s} {label}\n    base={base} model={model}")
        return

    if args.channel:
        os.environ["LLM_CHANNEL"] = args.channel

    pipe = RAGPipeline(_knowledge_dir())
    print(f"[channel={pipe.settings.channel} model={pipe.settings.model}]", file=os.sys.stderr)

    if args.query:
        print(json.dumps(pipe.ask(" ".join(args.query)), ensure_ascii=False, indent=2))
        return

    if not os.isatty(0):
        print("非交互环境：请用命令行参数传入问题，例如 python -m src.cli \"问题\"")
        return

    print("金融产品问答助手（输入 exit 退出）")
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
