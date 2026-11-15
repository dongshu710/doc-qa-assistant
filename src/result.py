"""一次问答的结果结构（`AskResult`）。

为什么单独一个文件：这个 dict 有 40 多个键，被五处消费——`openai_compat` 转 SDK 响应、
`report` 算指标、`handlers/write` 记审计与成本、`client_api` 交给桌面/终端客户端、
前端直接读 JSON。键名拼错不会报错，只会静默返回 `None`，然后表现成「某个指标永远是 0」。

全仓有 16 个 dataclass，唯独这个最复杂的结构是自由 dict。这里只是把契约写下来：
运行时不校验（TypedDict 就是个带注解的 dict），但 IDE 能补全、读代码的人能一眼看到
有哪些字段、哪个字段是「降级可见」那一组。

维护约定：`pipeline.py` 里新增一个 `result[...] =` 就补一个键。
`tests/test_result_contract.py` 会比对「源码里出现过的键」与「这里声明的键」，
漏了会红——否则这份声明过两周就和实现分叉了。
"""
from __future__ import annotations

from typing import Any, TypedDict


class AskResult(TypedDict, total=False):
    """一次问答的完整结果。全部键可选：不同分支只填自己产出的部分。"""

    # ---------- 身份与上下文 ----------
    trace_id: str
    query: str
    session_id: str | None
    context_query: str | None      # 改写后的问题；与原问题相同时为 None
    turn: int | None
    channel: str
    request_id: str
    ts: str

    # ---------- 模型与分流 ----------
    model: str
    model_override: str | None
    path: str                      # rag | keyword（本地直出）
    api_called: bool
    canary: bool
    budget_blocked: bool

    # ---------- 结果 ----------
    behavior: str                  # answer | refuse | ask_clarify | no_answer | ...
    answer: str
    answer_completed_reason: str | None
    confidence: str                # high | medium | low | none
    similar_questions: list
    error: str | None

    # ---------- 检索 ----------
    citations: list
    retrieved: list
    retrieval_score: float
    retrieval_mode: str
    search_query: str | None
    gate_score: float
    mode: str | None
    min_score: float
    kb_version: str | None
    keyword_gate: str | None
    keyword_rejected: bool
    keyword_stale: bool
    keyword_error: str | None
    # 关键词直出的诊断：命中哪些文档、哪些词、极性是否冲突。页面「来源」抽屉用它
    # 解释「为什么这条是直出而不是模型答的」。
    keyword_docs: list
    keyword_kinds: list
    keyword_terms: list
    keyword_polarity: str | None

    # ---------- 引用校验 ----------
    citation_coverage: float
    citation_repaired: bool
    citation_exempt_reason: str | None
    citation_support: list
    citation_support_checked: int
    citation_support_rate: float

    # ---------- 成本与耗时 ----------
    latency_ms: float
    cost_usd: float
    usage: dict
    embedding_tokens: int

    # ---------- 降级可见（这一组是「不静默失败」的骨架，别因为可选就漏掉）----------
    degraded: bool
    degrade_reason: str | None
    retrieval_error: str | None
    expansion_error: str | None


# 允许消费方在结果里塞自己的附加字段（例如 handler 层加的内部标记）而不改这个契约。
AskResultExtras = dict[str, Any]
