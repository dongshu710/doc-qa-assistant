"""编排层：输入校验 → 检索 → 生成 → 引用校验 → 观测。

设计取舍：文档问答本质是「检索→生成→引用」的固定链路（Prompt Chaining），
不是自主 Agent。这里如实按工作流实现；只有未来接入多工具动态调用（查利率 API、算 IRR、转工单）
才升级为有界 Agent。详见 README 的「何时才升级为 Agent」。

本轮优化：
- 输入归一化（去零宽/控制字符），拦截零宽注入；
- 检索置信度闸门（min_score），低置信按未命中转人工；
- 引用强制：LLM 回答若不含有效 [n]，降级为可追溯的抽取式（金融场景不接受无出处答案）。
"""
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone

from .chunking import load_corpus
from .config import api_key, load_settings
from .embeddings import EmbeddingError, EmbeddingUnavailable
from .generator import extractive_answer, generate, repair_citation
from .keywords import KeywordIndex

# 最外层拦截：通用护栏（注入/越权/隐私）+ profile 附加护栏（金融：荐股/收益承诺）
from .profiles import get_profile
from .profiles import refuse_patterns as _refuse_patterns
from .query import expand
from .retriever import build_retriever
from .suggest import similar as similar_questions

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060\ufeff\u00ad]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _normalize(text: str) -> str:
    """去掉零宽字符与控制字符，防止用零宽字符绕过注入检测。"""
    return _CONTROL.sub("", _ZERO_WIDTH.sub("", text)).strip()


def _build_vocabulary(chunks, limit: int = 30) -> list[str]:
    """知识库章节词表，供查询扩展使用（让改写贴合文档自身术语）。

    只取标题/章节名，不取正文：既省 token，也避免把答案内容提前喂给改写器。
    """
    seen, out = set(), []
    for c in chunks:
        key = c.title if c.section in ("", "概述") else f"{c.title}·{c.section}"
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out[:limit]


class RAGPipeline:
    def __init__(self, knowledge_dir: str):
        self.settings = load_settings()
        self.knowledge_dir = knowledge_dir
        self.chunks = load_corpus(knowledge_dir)
        if not self.chunks:
            raise ValueError("知识库为空，无法启动")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = root
        self.log_path = os.path.join(root, "logs", "trace.jsonl")
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self._retrieval_error: str | None = None
        self.retriever = self._make_retriever(self.chunks)
        self.vocabulary = _build_vocabulary(self.chunks)
        # 启动时只做本地抽取：有 Key 时也不在启动阶段打模型，避免首屏被拖慢
        self.keywords = self._make_keywords(self.chunks, enrich=False)

    def _index_dir(self) -> str:
        configured = self.settings.embedding_index_dir or "data/index"
        return configured if os.path.isabs(configured) else os.path.join(self.project_root, configured)

    def _make_retriever(self, chunks):
        """embedding 不可用时回退 hashing 向量，并把原因留在 retrieval_detail。"""
        try:
            return build_retriever(chunks, self.settings.retrieval, self.settings.rrf_k,
                                   settings=self.settings, index_dir=self._index_dir())
        except EmbeddingUnavailable as exc:
            self._retrieval_error = str(exc)
            return build_retriever(chunks, "vector")
        except EmbeddingError as exc:
            # 模型/索引不可用（网络、维度错、索引损坏）：降级但显式暴露，不静默
            self._retrieval_error = f"{type(exc).__name__}: {exc}"[:300]
            return build_retriever(chunks, "vector")

    def _make_keywords(self, chunks, enrich: bool):
        configured = self.settings.keyword_index or "data/index/keywords.json"
        path = configured if os.path.isabs(configured) else os.path.join(self.project_root, configured)
        index = KeywordIndex(chunks, self.settings, path)
        try:
            index.ensure(enrich=enrich)
        except Exception as exc:  # noqa: BLE001 —— 关键词只是加速路径，坏了不能拖垮主链路
            index.last_error = f"构建失败: {type(exc).__name__}: {exc}"[:200]
        return index

    @property
    def keyword_detail(self) -> dict:
        detail = self.keywords.describe()
        detail["mode"] = self.settings.keyword_mode
        detail["llm_mode"] = self.settings.keyword_llm
        detail["error"] = self.keywords.last_error
        return detail

    @property
    def retrieval_detail(self) -> dict:
        detail = self.retriever.describe()
        detail["configured_mode"] = self.settings.retrieval
        detail["fallback_error"] = self._retrieval_error
        return detail

    @property
    def llm_ready(self) -> bool:
        """是否具备调用真实模型的条件（有 Key）；否则走离线抽取。"""
        return bool(api_key())

    def ask(self, query: str, model: str | None = None, force_extractive: bool = False) -> dict:
        trace_id = uuid.uuid4().hex[:12]
        t0 = time.time()
        raw_query = query or ""
        clean = _normalize(raw_query)
        result = {
            "trace_id": trace_id,
            "query": raw_query,
            "channel": self.settings.channel,
            "model": model or self.settings.model,
            "model_override": model,
            "behavior": "answer",
            "answer": "",
            "path": "rag",              # rag | keyword：keyword 表示本地直出
            "api_called": False,        # 本次是否调用过任何模型/embedding 接口
            "citations": [],
            "retrieved": [],
            "retrieval_score": 0.0,
            "retrieval_mode": self.retriever.describe().get("mode", self.settings.retrieval),
            "search_query": None,
            "gate_score": 0.0,
            "mode": None,
            "degraded": False,
            "degrade_reason": None,
            "citation_coverage": 0.0,
            "citation_repaired": False,
            "latency_ms": 0.0,
            "cost_usd": 0.0,
        }

        # ---------- 输入校验（最外层，先拦脏数据与红线）----------
        if not clean:
            result.update(behavior="ask_clarify", answer="请提供您要咨询的具体问题。")
            return self._finish(result, t0)
        if len(clean) > self.settings.max_input_chars:
            result.update(
                behavior="ask_clarify",
                answer=f"问题过长（>{self.settings.max_input_chars} 字），请精简后重试。",
            )
            return self._finish(result, t0)
        for pat in _refuse_patterns(get_profile(self.settings.profile)):
            if re.search(pat, clean, re.IGNORECASE):
                result.update(behavior="refuse", answer="抱歉，这个请求我无法处理。")
                return self._finish(result, t0)

        # ---------- 关键词直出（本地，不调用任何 API）----------
        # 放在检索之前：命中即答，省掉 embedding 与生成两次调用，也避免模型改写引入偏差。
        # 只对结构化条目生效（清单/表格/标签/显式关键词），标题与普通词不在此列。
        # 命中后还要过否定、极性、解释型意图、单文档四道闸门；被挡下的原因写入 trace。
        if self.settings.keyword_mode != "off" and not force_extractive:
            try:
                report = self.keywords.match_report(clean)
            except Exception as exc:  # noqa: BLE001 —— 关键词匹配失败就退回正常检索
                report = None
                result["keyword_error"] = f"{type(exc).__name__}: {exc}"[:200]
            if report is not None:
                if report.gate:
                    result["keyword_gate"] = report.gate
                if report.rejected:
                    result["keyword_rejected"] = report.rejected
                # 同一条原文只算一次：引用编号必须与答案里的 [n] 一致
                kw_hits = KeywordIndex.merge(report.hits)
                if kw_hits:
                    citations, retrieved = [], []
                    for i, hit in enumerate(kw_hits, 1):
                        chunk = self.keywords.chunks[hit.entry.chunk_index]
                        citations.append({"ref": i, "title": chunk.title, "section": chunk.section})
                        retrieved.append({"title": chunk.title, "section": chunk.section,
                                          "score": round(hit.score, 3)})
                    result.update(
                        behavior="answer",
                        mode="keyword_local",
                        path="keyword",
                        api_called=False,
                        answer=KeywordIndex.compose(kw_hits),
                        citations=citations,
                        retrieved=retrieved,
                        retrieval_score=round(kw_hits[0].score, 4),
                        gate_score=round(kw_hits[0].score, 4),
                        citation_coverage=1.0,
                        keyword_terms=list(dict.fromkeys(h.entry.term for h in kw_hits)),
                        keyword_docs=list(dict.fromkeys(h.entry.doc_id for h in kw_hits)),
                        keyword_kinds=list(dict.fromkeys(h.entry.kind for h in kw_hits)),
                        keyword_polarity=list(dict.fromkeys(h.entry.polarity for h in kw_hits)),
                    )
                    return self._finish(result, t0)

        # ---------- 检索 ----------
        # 查询扩展只作用于检索；给模型的仍然是用户原问题（避免改写引入偏差）
        search_query = clean
        expanded = False
        if len(clean) >= 6:
            expansion_on = self.settings.query_expansion == "llm" or (
                self.settings.query_expansion == "auto" and bool(api_key())
            )
            if expansion_on:
                search_query, expanded = expand(clean, self.vocabulary)
        result["search_query"] = search_query if expanded else None
        result["api_called"] = bool(expanded)  # 查询扩展会调用模型

        try:
            hits = self.retriever.search(search_query, self.settings.top_k, focus_query=clean)
        except Exception as exc:  # noqa: BLE001 —— 检索异常降级为不检索，且显式标注
            hits = []
            result["degraded"] = True
            result["degrade_reason"] = "retrieval_error"
            result["retrieval_error"] = str(exc)

        if hits:
            result["retrieval_score"] = hits[0][1]

        # 检索层降级必须可见：embedding 超时/限流/维度错时当次已回退 BM25
        embed_error = getattr(self.retriever, "last_error", None)
        if embed_error:
            result["degraded"] = True
            result["degrade_reason"] = "embedding_error"
            result["retrieval_error"] = str(embed_error)[:300]
        embed_usage = getattr(self.retriever, "last_usage", {}) or {}
        if embed_usage.get("total_tokens"):
            result["embedding_tokens"] = int(embed_usage["total_tokens"])
            result["api_called"] = True

        # 置信度闸门：**用原问题的检索分**判断是否域外。
        # 若用扩展后的分数，域外问题会被扩展词“拉近”而误答（实测「今天天气」被打成 answer）。
        gate_score = hits[0][1] if hits else 0.0
        if expanded:
            try:
                orig = self.retriever.search(clean, 1)
                gate_score = orig[0][1] if orig else 0.0
            except Exception:  # noqa: BLE001 —— 复核失败就退回扩展后的分数
                pass
        result["gate_score"] = gate_score

        # 低置信不硬答，转人工，避免“看起来像答案”的幻觉
        if not hits or gate_score < self.settings.min_score:
            result.update(
                behavior="no_answer",
                answer="没有在文档中找到相关问题。",
                similar_questions=similar_questions(self.chunks, clean, hits, 3),
            )
            return self._finish(result, t0)

        # ---------- 生成 ----------
        gen = generate(clean, hits, model=model, force_extractive=force_extractive)
        result["mode"] = gen["mode"]
        result["api_called"] = bool(result["api_called"] or gen["mode"] == "llm")
        result["degraded"] = bool(gen["degraded"] or result["degraded"])
        result["answer"] = gen["answer"]
        result["usage"] = gen.get("usage", {})
        if force_extractive and self.llm_ready:
            result["degraded"] = True
            result["degrade_reason"] = "budget_exceeded"
        if gen["mode"] == "extractive_fallback":
            result["degrade_reason"] = "llm_error"
        if gen.get("error"):
            result["error"] = gen["error"]  # 降级原因必须可见，禁止静默

        # ---------- 引用校验 ----------
        cited = [int(x) for x in re.findall(r"\[(\d+)\]", gen["answer"])]
        valid = sorted({n for n in cited if 1 <= n <= len(hits)})

        # 引用强制：LLM 若给出无出处答案，先尝试补引用；补不上再降级为可追溯的抽取式答案
        # 例外：「资料未提供」类回答天然无出处，强制降级只会得到更差的答案，故豁免（并在 trace 标记）
        _NO_INFO = re.compile(r"(资料中|资料库中)?(未找到|未提供|未提及|未披露|未明确|未规定|没有(相关)?(说明|规定|提及))")
        if gen["mode"] == "llm" and not valid and _NO_INFO.search(gen["answer"]):
            result["citation_exempt_reason"] = "insufficient_info"
            result["similar_questions"] = similar_questions(self.chunks, clean, hits, 3)
            # 模型常只回一句「资料中未找到。」：诚实但不可用，补上转人工指引（不新增任何事实）
            if len(gen["answer"]) < 40:
                result["answer"] = (
                    "资料库中未找到与该问题相关的明确说明，建议转人工或咨询网点客户经理确认。"
                )
                result["answer_completed_reason"] = "insufficient_info"

        if gen["mode"] == "llm" and not valid and not result.get("citation_exempt_reason"):
            repaired = None
            try:
                repaired = repair_citation(clean, hits, gen["answer"])
            except Exception as exc:  # noqa: BLE001 —— 补引用失败不应影响主流程
                result["error"] = f"citation_repair_failed: {exc}"
            if repaired:
                r_cited = [int(x) for x in re.findall(r"\[(\d+)\]", repaired)]
                r_valid = sorted({n for n in r_cited if 1 <= n <= len(hits)})
                if r_valid:
                    result["answer"] = repaired
                    result["citation_repaired"] = True
                    cited, valid = r_cited, r_valid

            if not valid:
                fallback = extractive_answer(clean, hits)
                result["answer"] = fallback
                result["mode"] = "extractive_fallback"
                result["degraded"] = True
                result["degrade_reason"] = "no_citation"
                cited = [int(x) for x in re.findall(r"\[(\d+)\]", fallback)]
                valid = sorted({n for n in cited if 1 <= n <= len(hits)})

        result["citations"] = [
            {"ref": n, "title": hits[n - 1][0].title, "section": hits[n - 1][0].section}
            for n in valid
        ]
        result["citation_coverage"] = round(len(valid) / len(cited), 3) if cited else 0.0
        result["retrieved"] = [
            {"title": c.title, "section": c.section, "score": round(s, 3)} for c, s in hits
        ]
        return self._finish(result, t0)

    def reload(self) -> int:
        """重新加载知识库（知识库页上传/删除、版本审批后调用）。"""
        chunks = load_corpus(self.knowledge_dir)
        if not chunks:
            raise ValueError("知识库为空，拒绝加载")
        self._retrieval_error = None
        retriever = self._make_retriever(chunks)
        # 先构建成功再替换，避免构建失败把在线检索打空
        self.chunks = chunks
        self.retriever = retriever
        self.vocabulary = _build_vocabulary(chunks)
        # 上传/审批后重建：只对新增或变更的文档做一次模型整理，其余走缓存
        self.keywords = self._make_keywords(chunks, enrich=True)
        return len(chunks)

    def rebuild_keywords(self, enrich: bool = True) -> dict:
        """只重建关键词（不动检索索引）；enrich=True 时对变更文档做一次模型整理。"""
        self.keywords = self._make_keywords(self.chunks, enrich=enrich)
        return self.keyword_detail

    def _finish(self, result: dict, t0: float) -> dict:
        result["latency_ms"] = round((time.time() - t0) * 1000, 1)
        result["ts"] = datetime.now(timezone.utc).isoformat()
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 日志失败不影响主流程；生产环境此处应告警
        return result
