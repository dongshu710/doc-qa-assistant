"""Dify 外部知识库适配：把本项目的检索结果翻译成 Dify 的 records 协议。

为什么只做检索、不做问答：
外部知识库的语义是「给 Dify 提供上下文，由它自己的模型生成答案」。如果这里顺带
调一次 LLM，一次提问就烧两次钱；更糟的是 Dify 会拿到一段已经写好的答案，它只会
把那段话复述一遍，本项目的引用编号与「无法找到答案」的拒答语义全部失效。
两边的护栏互相抵消，等于既多花钱又更不可控。

协议来源：Dify 官方 External Knowledge API（`POST {endpoint}/retrieval`）。
字段与取值必须在服务端严格校验——Dify 自己发的请求一定合法，但把同一个端点
挂到别处（脚本、其他平台）时未必，少一个类型判断就是一个 500。
"""
from __future__ import annotations

# Dify 面板上的 top_k 一般是 3–5；上限只是防「传 1000 把索引扫穿」。
# 调大没有意义：Dify 最终只把前若干条拼进上下文，多召回只会拖慢这次请求。
MAX_TOP_K = 20
DEFAULT_TOP_K = 4


class DifyError(ValueError):
    """请求不合法。带 Dify 约定的 error_code，便于对方按码分流。"""

    def __init__(self, message: str, code: int = 1001):
        super().__init__(message)
        self.code = code


def _as_int(value, name: str, default: int) -> int:
    """bool 是 int 的子类，`top_k=True` 会静默变成 1——先把它挡掉。"""
    if value is None:
        return default
    if isinstance(value, bool):
        raise DifyError(f"{name} 需为正整数")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise DifyError(f"{name} 需为正整数") from None


def _as_score(value, name: str) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        raise DifyError(f"{name} 需为 0–1 之间的小数")
    try:
        score = float(value)
    except (TypeError, ValueError):
        raise DifyError(f"{name} 需为 0–1 之间的小数") from None
    if score != score:              # NaN：比较永远为假，会一路漏到排序里
        raise DifyError(f"{name} 需为 0–1 之间的小数")
    return max(0.0, min(1.0, score))


def parse_request(payload: dict) -> tuple[str, int, float]:
    """从 Dify 的请求体里取 (query, top_k, score_threshold)。

    `query` 允许为空串——这不是宽容，是必需：Dify 保存「外部知识库 API」时会发一次
    探针请求，body 是 `{"knowledge_id": "", "query": "", "retrieval_setting": {...}}`。
    对空查询回 400 也能「碰巧」通过（它只把 502/404/403 当失败），但那是靠对方不检查
    400 才成立的，换个版本就断。正确做法是回 `{"records": []}`：空查询本来就检不出
    任何东西，这正是它对检索的真实语义。
    """
    if not isinstance(payload, dict):
        raise DifyError("请求体必须是 JSON 对象")
    if "query" not in payload:
        raise DifyError("缺少 query")
    query = payload.get("query")
    if not isinstance(query, str):
        raise DifyError("query 必须是字符串")
    setting = payload.get("retrieval_setting") or {}
    if not isinstance(setting, dict):
        raise DifyError("retrieval_setting 必须是对象")
    top_k = _as_int(setting.get("top_k"), "top_k", DEFAULT_TOP_K)
    if top_k <= 0:
        raise DifyError("top_k 需为正整数")
    top_k = min(top_k, MAX_TOP_K)
    threshold = _as_score(setting.get("score_threshold"), "score_threshold")
    return query.strip(), top_k, threshold


def _content_of(chunk) -> str:
    """拼给模型的正文。

    首行带「文档名 · 小节」不是装饰：Dify 只把 content 拼进上下文，不把 title
    交给模型。没有这一行，模型写得出答案却说不出来源，本项目「引用可核」的
    主张在 Dify 里就直接失效了。
    """
    body = (chunk.text or "").strip()
    head = " · ".join(part for part in ((chunk.doc_id or "").strip(),
                                        (chunk.section or "").strip()) if part)
    return f"{head}\n{body}" if head else body


def records(pipe, query: str, top_k: int, threshold: float = 0.0) -> list[dict]:
    """检索并转成 Dify 的 records。

    检索走 `pipeline._retrieve` 而不是自己拼 retriever：那里已经处理了
    「新实现有 search_ex、老实现只有 search」的兼容，也把 meta 从返回值带走，
    绕开它等于把并发串账的风险又写一遍。

    空查询直接返回空列表，不碰检索器：Dify 的探针请求就是空 query，
    为它跑一次 embedding 既浪费，也会把「探针通过」变成「连接失败」。
    """
    if not (query or "").strip():
        return []
    hits, _meta = pipe._retrieve(query, top_k=top_k)   # noqa: SLF001 —— 同包内部适配层
    out: list[dict] = []
    for chunk, score in hits:
        try:
            value = float(score)
        except (TypeError, ValueError):
            continue
        if value != value:          # NaN
            continue
        value = max(0.0, min(1.0, value))
        if threshold and value < threshold:
            continue
        out.append({
            "content": _content_of(chunk),
            "score": round(value, 4),
            "title": (chunk.doc_id or "").strip() or "未命名文档",
            # metadata 必须是对象：Dify 明确说 null 会让检索流水线报错
            "metadata": {
                "doc": chunk.doc_id,
                "section": chunk.section,
                "chunk": chunk.chunk_index,
            },
        })
    return out
