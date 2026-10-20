"""构建 / 校验 embedding 索引（迁移与运维入口）。

用法：
    # 用当前活动知识库版本构建（先跑一次服务或手动 bootstrap）
    python tools/build_index.py
    # 强制重建（语料/模型变了但想立刻重算，不等首次查询）
    python tools/build_index.py --rebuild
    # 构建完抽查几条问题
    python tools/build_index.py --check "大额存单可以转让吗"

输出是 JSON，便于 CI/运维脚本读取：backend、dim、chunks、build_usage、index_dir。
失败返回非 0：未配置模型、维度不一致、embedding 服务不可达都会显式报错。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.chunking import load_corpus  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.embeddings import EmbeddingError, make_provider  # noqa: E402
from src.retriever import EmbeddingRetriever  # noqa: E402


def active_knowledge_dir(project_root: str) -> str:
    state_path = os.path.join(project_root, "data", "kb", "state.json")
    if os.path.exists(state_path):
        try:
            with open(state_path, encoding="utf-8") as f:
                active = json.load(f).get("active")
            if active:
                path = os.path.join(project_root, "data", "kb", "versions", active, "files")
                if os.path.isdir(path):
                    return path
        except (OSError, json.JSONDecodeError):
            pass
    return os.path.join(project_root, "data", "knowledge")


def main() -> int:
    ap = argparse.ArgumentParser(description="构建 embedding 索引")
    ap.add_argument("--knowledge-dir", help="默认取当前活动知识库版本目录")
    ap.add_argument("--index-dir", help="默认 data/index（相对项目根）")
    ap.add_argument("--store", help="auto | pure | numpy | faiss | faiss-ivf")
    ap.add_argument("--rebuild", action="store_true", help="删除旧索引元数据后重建（保留 embedding 缓存）")
    ap.add_argument("--check", action="append", default=[], help="构建后抽查的问题，可重复")
    args = ap.parse_args()

    settings = load_settings()
    try:
        provider = make_provider(settings)
    except EmbeddingError as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2
    if provider is None:
        print(json.dumps({"ok": False, "error": "未配置 EMBEDDING_PROVIDER/BASE_URL/MODEL"}, ensure_ascii=False))
        return 2

    knowledge_dir = args.knowledge_dir or active_knowledge_dir(ROOT)
    chunks = load_corpus(knowledge_dir)
    if not chunks:
        print(json.dumps({"ok": False, "error": f"知识库为空: {knowledge_dir}"}, ensure_ascii=False))
        return 2

    index_dir = args.index_dir or settings.embedding_index_dir
    if not os.path.isabs(index_dir):
        index_dir = os.path.join(ROOT, index_dir)

    if args.rebuild:
        for name in ("manifest.json", "vectors.jsonl", "index.faiss"):
            try:
                os.remove(os.path.join(index_dir, name))
            except FileNotFoundError:
                pass

    store_kind = args.store or settings.vector_store
    try:
        retriever = EmbeddingRetriever(chunks, provider, index_dir, store_kind=store_kind,
                                       recall_k=settings.embedding_recall_k,
                                       nlist=settings.vector_ivf_nlist,
                                       nprobe=settings.vector_ivf_nprobe)
    except EmbeddingError as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 3

    summary = {
        "ok": True,
        "knowledge_dir": knowledge_dir,
        "chunks": len(chunks),
        **retriever.index_status,
    }
    checks = []
    for query in args.check:
        hits = retriever.search(query, 3)
        checks.append({
            "query": query,
            "top": [{"title": c.title, "section": c.section, "score": s} for c, s in hits],
            "embedding_error": retriever.last_error,
        })
    if checks:
        summary["checks"] = checks
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
