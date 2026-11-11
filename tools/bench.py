"""可复现的基准测试：检索延迟、索引构建、笔记检索。

为什么需要：选型时最常被问的是「规模上去还快吗」。没有公开数字时，答案只能是
「应该还行」，而这句话对使用者没有价值。这里给的是**可复现的**数字：
同一台机器、同一段脚本、同一批合成语料，跑一次就能对上。

诚实边界（数字旁边必须写）：
- 合成语料，不是公开数据集；它测的是「实现的开销」，不是「答案的质量」。
- 数字与 CPU 强相关。同一份脚本在不同机器上差 2–3 倍是正常的，
  所以报告里同时记录核数与 Python 版本。
- 只测纯 Python 路径（默认配置）。装了 numpy/faiss 会更快，但那是另一条路径。

用法：
    python tools/bench.py                      # 打印 Markdown 表
    python tools/bench.py --write              # 写入 docs/BENCHMARK.md
    python tools/bench.py --sizes 1000,5000    # 指定规模
"""
from __future__ import annotations

import argparse
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SECTIONS = [
    "产品要素", "申购与赎回", "费率与收费", "风险揭示", "适当性管理",
    "信息披露", "投诉与处理", "附则",
]
WORDS = ["稳盈系列", "起购金额", "管理费率", "赎回费", "持有期限", "风险等级",
         "合格投资者", "销售适当性", "信息披露", "托管费率", "业绩比较基准"]


def make_chunks(count: int):
    """合成语料：条款式短文本，贴近真实制度文件的分块长度（~120 字）。"""
    from src.chunking import Chunk
    chunks = []
    for index in range(count):
        head = WORDS[index % len(WORDS)]
        tail = WORDS[(index * 7 + 3) % len(WORDS)]
        text = (f"第{index % 50 + 1}条 关于{head}的规定。"
                f"本条款适用于{tail}相关情形，具体以合同约定为准。" * 3)
        chunks.append(Chunk(doc_id=f"doc{index // 40}", title=f"制度{index // 40}",
                            section=SECTIONS[index % len(SECTIONS)], text=text,
                            chunk_index=index % 40))
    return chunks


def _isolated(job: str, *args) -> dict:
    """在独立进程里跑一个用例，拿回 JSON。

    为什么要这样做：同进程跑多组大用例时，前面用例留下的几百 MB 对象会让
    后面每一次点积都变慢（实测同一份 5000×1024 数据，干净进程 105 ms，
    被污染后 605 ms）。基准数字不可信比没有基准更糟——它会让人做出错误的选型。
    """
    import json
    import subprocess
    command = [sys.executable, str(Path(__file__).resolve()), "--internal", job]
    for name, value in zip(("size", "dim"), args):
        command += [f"--{name}", str(value)]
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", env=dict(os.environ, BENCH_INTERNAL="1"))
    if result.returncode != 0:
        raise RuntimeError(f"基准子进程失败（{job}）：{result.stderr.strip()[:300]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def timeit(fn, repeat: int = 5) -> float:
    """跑 repeat 次取中位数（毫秒）。

    计时期间关掉 GC：一轮检索会临时产生几万个临时对象，GC 恰好在计时窗口里
    触发一次就能把数字抬高 3 倍（实测同一份 5000×1024 数据在 100–600 ms 之间跳）。
    每次计时前先 `gc.collect()`，保证起点一致。
    """
    import gc
    samples = []
    for _ in range(repeat):
        gc.collect()
        gc.disable()
        try:
            started = time.monotonic()
            fn()
            samples.append((time.monotonic() - started) * 1000)
        finally:
            gc.enable()
    return statistics.median(samples)


def bench_retrieval(sizes: list[int]) -> list[dict]:
    rows = []
    for size in sizes:
        data = _isolated("retrieval", size)
        for mode in ("bm25", "vector"):
            rows.append({"size": size, "mode": mode, "ms": data[mode]})
    return rows


def run_retrieval(size: int) -> dict:
    """单个规模的检索延迟。只在子进程里调用。"""
    from src.retriever import build_retriever
    query = "稳盈系列产品的起购金额是多少"
    chunks = make_chunks(size)
    out = {}
    for mode in ("bm25", "vector"):
        retriever = build_retriever(chunks, mode)
        retriever.search(query, 4)          # 预热：首次调用含懒初始化
        out[mode] = timeit(lambda: retriever.search(query, 4))
    return out


def bench_build(sizes: list[int]) -> list[dict]:
    """切分 + 索引构建（不含 embedding 网络调用）。"""
    from src.chunking import parse_document
    from src.keywords import KeywordIndex
    rows = []
    for size in sizes:
        # 一份「文档」里放 size 条条款，模拟单文档大文件
        raw = "# 制度汇编\n\n## 条款\n" + "\n".join(
            f"第{i % 80 + 1}条 关于{WORDS[i % len(WORDS)]}的规定。具体以合同约定为准。" * 2
            for i in range(size))
        parsed = timeit(lambda: parse_document(raw, "big.md"), repeat=3)
        chunks = parse_document(raw, "big.md")
        built = timeit(lambda: KeywordIndex(chunks), repeat=3)
        rows.append({"size": size, "chunks": len(chunks),
                     "parse_ms": parsed, "keyword_ms": built})
        del chunks
    return rows


def bench_store(sizes: list[int], dims: list[int]) -> list[dict]:
    """向量库本身的内积开销（与检索算法无关的那部分）。

    单独测它是为了给出「规模 × 维度」的表格：决定要不要装 numpy/faiss 的是这个数，
    而不是端到端延迟——端到端里混着切分、重排、IO，看不出瓶颈在哪。
    """
    rows = []
    for size in sizes:
        for dim in dims:
            data = _isolated("store", size, dim)
            rows.append({"size": size, "dim": dim, "ms": data["ms"]})
    return rows


def run_store(size: int, dim: int) -> dict:
    """单个（块数, 维度）用例。只在子进程里调用。"""
    import array
    import random

    from src.vector_store import PureFlatStore
    random.seed(7)
    store = PureFlatStore(dim)
    # 用生成器逐行喂：一次性建 `[[...]] * 20000` 会临时造出 65 万个 float 对象，
    # 那份垃圾在后面的计时里还在拖慢 GC（实测让 20000×1024 从 ~400ms 变成 2.4s）。
    store.add(array.array("f", (random.uniform(-1, 1) for _ in range(dim)))
              for _ in range(size))
    query = [random.uniform(-1, 1) for _ in range(dim)]
    store.search(query, 4)
    return {"ms": timeit(lambda: store.search(query, 4), repeat=3)}


def bench_notes(sizes: list[int]) -> list[dict]:
    from src.notes.search import NoteSearcher
    rows = []
    for size in sizes:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "notes").mkdir(exist_ok=True)
            wanted = []
            texts = {}
            for index in range(size):
                note_id = f"n{index:05d}"
                body = (f"第{index}篇 理财产品 起购金额 风险测评 "
                        + "稳盈系列产品的赎回费与期限说明 " * 30)
                path = home / "notes" / f"{note_id}.md"
                path.write_text(body, encoding="utf-8")
                stat = path.stat()
                wanted.append({"id": note_id, "mtime_ns": stat.st_mtime_ns,
                               "size": stat.st_size})
                texts[note_id] = body
            searcher = NoteSearcher(home, lambda entry: texts[entry["id"]])
            searcher.rebuild(wanted, want_vec=False)
            query = "稳盈系列产品的赎回费是多少"
            cold = timeit(lambda: searcher.search(query, wanted, semantic="off"), repeat=1)
            warm = timeit(lambda: searcher.search(query, wanted, semantic="off"), repeat=5)
            rows.append({"size": size, "cold_ms": cold, "warm_ms": warm})
    return rows


def render(retrieval: list[dict], builds: list[dict], notes: list[dict],
           stores: list[dict] | None = None) -> str:
    from src.version import __version__
    cpu = platform.processor() or platform.machine()
    cores = os.cpu_count() or 0
    lines = [
        "# 基准测试结果",
        "",
        "> 本文件由 `python tools/bench.py --write` 生成，请勿手改。",
        "",
        "## 环境",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| 版本 | v{__version__} |",
        f"| Python | {platform.python_version()} |",
        f"| 系统 | {platform.system()} {platform.release()} |",
        f"| CPU | {cpu}（{cores} 核） |",
        "",
        "## 口径",
        "",
        "- 语料是**合成**的条款文本，不是公开数据集：测的是实现开销，不是答案质量。",
        "- 只测纯 Python 路径（默认配置）。装了 numpy/faiss 会更快，那是另一条路径。",
        "- 延迟取 5 次中位数，已排除首次调用的懒初始化；计时期间关闭 GC（否则数字会跳 3 倍）。",
        "- 每个用例在**独立子进程**里跑：同进程连续测会让后面的用例被前面的内存拖慢。",
        "- 数字与 CPU 强相关，跨机器差 2–3 倍属正常；比较时请在同一台机器上重跑。",
        "",
        "## 检索延迟（top-4，单次）",
        "",
        "| 块数 | 模式 | 延迟 | 每千块 |",
        "|---:|---|---:|---:|",
    ]
    for row in retrieval:
        per_k = row["ms"] / max(1, row["size"]) * 1000
        lines.append(f"| {row['size']} | {row['mode']} | {row['ms']:.1f} ms | {per_k:.1f} ms |")

    lines += [
        "",
        "## 向量库内积（纯 Python，精确检索）",
        "",
        "| 块数 | 维度 | 单次检索 | 每千块 |",
        "|---:|---:|---:|---:|",
    ]
    for row in stores or []:
        per_k = row["ms"] / max(1, row["size"]) * 1000
        lines.append(f"| {row['size']} | {row['dim']} | {row['ms']:.1f} ms | {per_k:.1f} ms |")

    lines += [
        "",
        "## 索引构建（单份大文档）",
        "",
        "| 输入条款数 | 切分块数 | 切分耗时 | 关键词索引耗时 |",
        "|---:|---:|---:|---:|",
    ]
    for row in builds:
        lines.append(f"| {row['size']} | {row['chunks']} | {row['parse_ms']:.0f} ms "
                     f"| {row['keyword_ms']:.0f} ms |")

    lines += [
        "",
        "## 笔记检索（词面通道）",
        "",
        "| 笔记数 | 首次（含分词） | 之后（缓存命中） |",
        "|---:|---:|---:|",
    ]
    for row in notes:
        lines.append(f"| {row['size']} | {row['cold_ms']:.1f} ms | {row['warm_ms']:.1f} ms |")

    # 结论必须由本次实测算出来。写死「约 100 ms/5000 块」这种话，
    # 换了机器或改了实现就会变成假话——而这些文字正是别人选型的依据。
    vector_rows = [r for r in retrieval if r["mode"] == "vector"]
    bm25_rows = [r for r in retrieval if r["mode"] == "bm25"]
    lines += ["", "## 怎么读这些数字", ""]
    if vector_rows and bm25_rows:
        big_v = max(vector_rows, key=lambda r: r["size"])
        big_b = max(bm25_rows, key=lambda r: r["size"])
        per_k_v = big_v["ms"] / max(1, big_v["size"]) * 1000
        extrapolated = per_k_v * 50
        lines.append(
            f"- `vector`（纯 Python，含重排）在 {big_v['size']} 块时 {big_v['ms']:.1f} ms，"
            f"折合每千块 {per_k_v:.1f} ms；按线性外推，5 万块约 {extrapolated:.0f} ms。")
        lines.append(
            f"- `bm25` 在 {big_v['size']} 块时 {big_b['ms']:.1f} ms。"
            f"词法检索的常数远小于向量内积，规模上去时它是更稳的兜底。")
        if extrapolated > 300:
            lines.append("- 结论：**按这条曲线，5 万块会超过 300 ms 首字预算**，"
                         "到那个规模建议装 `numpy`（自动走 `NumpyFlatStore`）"
                         "或改用 `bm25`/`hybrid`。")
        else:
            lines.append("- 结论：按本次实测外推，5 万块仍在几百毫秒内，"
                         "纯 Python 路径可用；再上一个数量级才需要考虑 `numpy`/`faiss`。")
    if stores:
        # 按维度分组看「每千块」是否随规模上升：上升说明瓶颈从 CPU 变成内存带宽，
        # 这种情况下加机器没用，只能换实现（numpy/faiss）。
        for dim in sorted({row["dim"] for row in stores}):
            group = sorted((r for r in stores if r["dim"] == dim), key=lambda r: r["size"])
            if len(group) < 2:
                continue
            small, big = group[0], group[-1]
            per_small = small["ms"] / small["size"] * 1000
            per_big = big["ms"] / big["size"] * 1000
            ratio = per_big / per_small if per_small else 0
            verdict = "基本线性" if ratio < 2 else f"每千块成本涨了 {ratio:.1f} 倍（内存带宽成了瓶颈）"
            lines.append(
                f"- 维度 {dim}：{small['size']} 块时每千块 {per_small:.1f} ms，"
                f"{big['size']} 块时 {per_big:.1f} ms —— {verdict}。")
    if notes:
        big_n = max(notes, key=lambda r: r["size"])
        lines.append(
            f"- 笔记检索 {big_n['size']} 篇：首次 {big_n['cold_ms']:.1f} ms，"
            f"缓存命中后 {big_n['warm_ms']:.1f} ms。首次的成本在分词，"
            f"它随篇数线性增长；命中后只剩打分。")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="可复现基准测试")
    parser.add_argument("--sizes", default="200,1000,5000",
                        help="检索规模（逗号分隔），默认 200,1000,5000")
    parser.add_argument("--build-sizes", default="200,1000",
                        help="构建规模（条款数）")
    parser.add_argument("--note-sizes", default="200,1000",
                        help="笔记数")
    parser.add_argument("--store-sizes", default="5000,20000",
                        help="向量库测试块数")
    parser.add_argument("--dims", default="256,1024",
                        help="向量维度")
    parser.add_argument("--write", action="store_true", help="写入 docs/BENCHMARK.md")
    parser.add_argument("--internal", help="（内部用）在子进程里跑单个用例")
    parser.add_argument("--size", type=int, help="（内部用）块数")
    parser.add_argument("--dim", type=int, help="（内部用）维度")
    args = parser.parse_args(argv)

    if args.internal:
        import json
        job = args.internal
        if job == "store":
            payload = run_store(int(args.size or 1000), int(args.dim or 256))
        elif job == "retrieval":
            payload = run_retrieval(int(args.size or 1000))
        else:
            print(f"未知用例 {job}", file=sys.stderr)
            return 2
        print(json.dumps(payload))
        return 0

    sizes = [int(item) for item in args.sizes.split(",") if item.strip()]
    build_sizes = [int(item) for item in args.build_sizes.split(",") if item.strip()]
    note_sizes = [int(item) for item in args.note_sizes.split(",") if item.strip()]

    print("检索延迟…", file=sys.stderr)
    retrieval = bench_retrieval(sizes)
    print("索引构建…", file=sys.stderr)
    builds = bench_build(build_sizes)
    print("向量库内积…", file=sys.stderr)
    store_sizes = [int(item) for item in args.store_sizes.split(",") if item.strip()]
    dims = [int(item) for item in args.dims.split(",") if item.strip()]
    stores = bench_store(store_sizes, dims)
    print("笔记检索…", file=sys.stderr)
    notes = bench_notes(note_sizes)

    text = render(retrieval, builds, notes, stores)
    if args.write:
        target = ROOT / "docs" / "BENCHMARK.md"
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"已写入 {target.relative_to(ROOT)}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
