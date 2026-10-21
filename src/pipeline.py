"""编排层：输入校验 → 检索 → 生成 → 引用校验 → 观测。

设计取舍：文档问答本质是「检索→生成→引用」的固定链路（Prompt Chaining），
不是自主 Agent。这里如实按工作流实现；只有未来接入多工具动态调用（查利率 API、算 IRR、转工单）
才升级为有界 Agent。详见 README 的「何时才升级为 Agent」。

本轮优化：
- 输入归一化（去零宽/控制字符），拦截零宽注入；
- 检索置信度闸门（min_score），低置信直接返回「无法找到答案」，不硬答；
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
from .generator import build_messages, extractive_answer, generate, repair_citation, stream_chat
from .keywords import KeywordIndex

# 最外层拦截：通用护栏（注入/越权/隐私）+ profile 附加护栏（金融：荐股/收益承诺）
from .profiles import get_profile
from .profiles import refuse_patterns as _refuse_patterns
from .query import expand
from .retriever import build_retriever
from .sessions import SessionStore
from .suggest import similar as similar_questions

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060\ufeff\u00ad]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# 追问线索：指代、转折、省略式问句。只有这些才把上一轮问题拼进来；
# 短问题不等于追问，「大额存单」这种话题切换不能硬拼上一轮。
_FOLLOWUP = re.compile(r"^(?:那|那么|这个|那个|它|还有|另外|如果|要是)|呢[？?]?$")


def _contextual_query(history, clean: str) -> str:
    """把省略式追问补成可检索的问题；独立问题原样返回。"""
    if not history:
        return clean
    last = (history[-1].query or "").strip()
    if not last:
        return clean
    if _FOLLOWUP.search(clean):
        return f"{last} {clean}"
    return clean


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
        self._chunk_pos = {id(chunk): i for i, chunk in enumerate(self.chunks)}
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = root
        self.log_path = os.path.join(root, "logs", "trace.jsonl")
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self._retrieval_error: str | None = None
        self.retriever = self._make_retriever(self.chunks)
        self.vocabulary = _build_vocabulary(self.chunks)
        self.sessions = SessionStore()
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

    def _prepare(self, query: str, model: str | None, force_extractive: bool,
                 session_id: str | None):
        """校验 → 关键词 → 检索 → 置信度闸门。

        返回 (result, ctx)：ctx 为 None 表示已经可以作答（澄清/拒答/直出/未命中），
        否则 ctx 里是生成所需的问题、命中块与计时起点。ask 与 ask_stream 共用这一层，
        保证两条路径的前置判断完全一致。
        """
        trace_id = uuid.uuid4().hex[:12]
        t0 = time.time()
        raw_query = query or ""
        clean = _normalize(raw_query)
        history = self.sessions.history(session_id)
        context_query = _contextual_query(history, clean)
        result = {
            "trace_id": trace_id,
            "query": raw_query,
            "session_id": session_id or None,
            "context_query": context_query if context_query != clean else None,
            "turn": (len(history) + 1) if session_id else None,
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
            return self._finish(result, t0), None
        if len(clean) > self.settings.max_input_chars:
            result.update(
                behavior="ask_clarify",
                answer=f"问题过长（>{self.settings.max_input_chars} 字），请精简后重试。",
            )
            return self._finish(result, t0), None
        for pat in _refuse_patterns(get_profile(self.settings.profile)):
            if re.search(pat, clean, re.IGNORECASE):
                result.update(behavior="refuse", answer="抱歉，这个请求我无法处理。")
                return self._finish(result, t0), None

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
                        citations.append(self._cite(chunk, i, KeywordIndex.snippet(hit)))
                        retrieved.append({"title": chunk.title, "section": chunk.section,
                                          "doc_id": chunk.doc_id,
                                          "chunk_index": hit.entry.chunk_index,
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
                    return self._finish(result, t0), None

        # ---------- 检索 ----------
        # 查询扩展只作用于检索；给模型的仍然是用户原问题（避免改写引入偏差）
        search_query = context_query
        expanded = False
        if len(context_query) >= 6:
            expansion_on = self.settings.query_expansion == "llm" or (
                self.settings.query_expansion == "auto" and bool(api_key())
            )
            if expansion_on:
                search_query, expanded = expand(context_query, self.vocabulary)
        result["search_query"] = search_query if expanded else None
        result["api_called"] = bool(expanded)  # 查询扩展会调用模型

        try:
            hits = self.retriever.search(search_query, self.settings.top_k, focus_query=context_query)
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
                orig = self.retriever.search(context_query, 1)
                gate_score = orig[0][1] if orig else 0.0
            except Exception:  # noqa: BLE001 —— 复核失败就退回扩展后的分数
                pass
        result["gate_score"] = gate_score

        # 低置信不硬答：直接说明无法找到答案，避免“看起来像答案”的幻觉
        if not hits or gate_score < self.settings.min_score:
            result.update(
                behavior="no_answer",
                answer="无法找到答案。",
                similar_questions=similar_questions(self.chunks, context_query, hits, 3),
            )
            return self._finish(result, t0), None

        return result, {"query": context_query, "hits": hits, "t0": t0,
                        "model": model, "force_extractive": force_extractive}

    def ask(self, query: str, model: str | None = None, force_extractive: bool = False,
            session_id: str | None = None) -> dict:
        result, ctx = self._prepare(query, model, force_extractive, session_id)
        if ctx is None:
            return result
        gen = generate(ctx["query"], ctx["hits"], model=model, force_extractive=force_extractive)
        return self._finalize(result, ctx, gen)

    def ask_stream(self, query: str, model: str | None = None, force_extractive: bool = False,
                   session_id: str | None = None):
        """流式版本：yield (event, payload)。

        event: delta（文本增量）| replace（整段替换）| final（完整结果）。
        非模型路径（关键词/拒答/未命中）只发 final；离线抽取发一次 delta 再发 final。
        """
        result, ctx = self._prepare(query, model, force_extractive, session_id)
        if ctx is None:
            yield "final", result
            return

        if ctx["force_extractive"] or not api_key():
            gen = generate(ctx["query"], ctx["hits"], model=ctx["model"], force_extractive=True)
            if gen["answer"]:
                yield "delta", gen["answer"]
        else:
            chunks: list[str] = []
            usage: dict = {}
            try:
                for delta in stream_chat(build_messages(ctx["query"], ctx["hits"]),
                                         model=ctx["model"], usage_out=usage):
                    chunks.append(delta)
                    yield "delta", delta
                answer = "".join(chunks).strip()
                if not answer:
                    raise RuntimeError("模型返回空内容")
                gen = {"mode": "llm", "answer": answer, "degraded": False,
                       "error": None, "usage": usage}
            except Exception as exc:  # noqa: BLE001 —— 半截输出不能重试，整体降级为抽取式
                gen = {"mode": "extractive_fallback",
                       "answer": extractive_answer(ctx["query"], ctx["hits"]),
                       "degraded": True, "error": str(exc), "usage": {}}
                yield "replace", gen["answer"]
        yield "final", self._finalize(result, ctx, gen)

    def _finalize(self, result: dict, ctx: dict, gen: dict) -> dict:
        """生成之后：引用校验、补引用、降级、引用回填。"""
        hits = ctx["hits"]
        context_query = ctx["query"]
        result["mode"] = gen["mode"]
        result["api_called"] = bool(result["api_called"] or gen["mode"] == "llm")
        result["degraded"] = bool(gen["degraded"] or result["degraded"])
        result["answer"] = gen["answer"]
        result["usage"] = gen.get("usage", {})
        if ctx["force_extractive"] and self.llm_ready:
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
            result["similar_questions"] = similar_questions(self.chunks, context_query, hits, 3)
            # 模型常只回一句「资料中未找到。」：诚实但不可用，统一成一句明确结论
            if len(gen["answer"]) < 40:
                result["answer"] = "无法找到答案。"
                result["answer_completed_reason"] = "insufficient_info"

        if gen["mode"] == "llm" and not valid and not result.get("citation_exempt_reason"):
            repaired = None
            try:
                repaired = repair_citation(context_query, hits, gen["answer"])
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
                fallback = extractive_answer(context_query, hits)
                result["answer"] = fallback
                result["mode"] = "extractive_fallback"
                result["degraded"] = True
                result["degrade_reason"] = "no_citation"
                cited = [int(x) for x in re.findall(r"\[(\d+)\]", fallback)]
                valid = sorted({n for n in cited if 1 <= n <= len(hits)})

        result["citations"] = [self._cite(hits[n - 1][0], n) for n in valid]
        result["citation_coverage"] = round(len(valid) / len(cited), 3) if cited else 0.0
        result["retrieved"] = [
            {"title": c.title, "section": c.section, "doc_id": c.doc_id,
             "chunk_index": self._chunk_pos.get(id(c), -1), "score": round(s, 3)}
            for c, s in hits
        ]
        return self._finish(result, ctx["t0"])

    def reload(self) -> int:
        """重新加载知识库（知识库页上传/删除、版本审批后调用）。"""
        chunks = load_corpus(self.knowledge_dir)
        if not chunks:
            raise ValueError("知识库为空，拒绝加载")
        self._retrieval_error = None
        retriever = self._make_retriever(chunks)
        # 先构建成功再替换，避免构建失败把在线检索打空
        self.chunks = chunks
        self._chunk_pos = {id(chunk): i for i, chunk in enumerate(chunks)}
        self.retriever = retriever
        self.vocabulary = _build_vocabulary(chunks)
        if not hasattr(self, "sessions"):
            self.sessions = SessionStore()
        # 上传/审批后重建：只对新增或变更的文档做一次模型整理，其余走缓存
        self.keywords = self._make_keywords(chunks, enrich=True)
        return len(chunks)

    def rebuild_keywords(self, enrich: bool = True) -> dict:
        """只重建关键词（不动检索索引）；enrich=True 时对变更文档做一次模型整理。"""
        self.keywords = self._make_keywords(self.chunks, enrich=enrich)
        return self.keyword_detail

    def _cite(self, chunk, ref: int, snippet: str = "") -> dict:
        """引用必须能回到原文：带 doc_id / chunk_index，前端可据此打开原文抽屉。"""
        return {
            "ref": ref, "title": chunk.title, "section": chunk.section,
            "doc_id": chunk.doc_id,
            "chunk_index": self._chunk_pos.get(id(chunk), -1),
            "snippet": snippet,
        }

    def source_chunk(self, doc_id: str, chunk_index: int) -> dict | None:
        """按引用定位原文；只接受当前索引里真实存在的块，不做文件路径拼接。"""
        if not (0 <= chunk_index < len(self.chunks)):
            return None
        chunk = self.chunks[chunk_index]
        if chunk.doc_id != doc_id:
            return None
        return {
            "doc_id": chunk.doc_id, "title": chunk.title, "section": chunk.section,
            "chunk_index": chunk_index, "text": chunk.text,
            "doc_chunks": sum(1 for c in self.chunks if c.doc_id == doc_id),
        }

    def _finish(self, result: dict, t0: float) -> dict:
        session_id = result.get("session_id")
        if session_id and result.get("answer"):
            self.sessions.append(session_id, result.get("query") or "", result["answer"])
        result["latency_ms"] = round((time.time() - t0) * 1000, 1)
        result["ts"] = datetime.now(timezone.utc).isoformat()
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 日志失败不影响主流程；生产环境此处应告警
        return result
