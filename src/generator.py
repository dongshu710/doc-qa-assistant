"""生成层：优先调用 OpenAI 兼容端点（默认 DeepSeek）；无 key 或调用失败时降级为离线抽取。

离线抽取不是「假跑」：它保证 检索→引用→校验 链路在没有任何密钥时也能端到端跑通与评测。
上线时只需注入 LLM_API_KEY（或 DEEPSEEK_API_KEY）即切换为真实大模型生成，其余链路不变。
"""
import json
import os
import random
import re
import time
import urllib.error
import urllib.request

from .config import api_key, load_settings
from . import injection
from .profiles import get_profile
from .retriever import tokenize


def system_prompt() -> str:
    """按当前 profile 取系统提示词（金融/通用）。"""
    return get_profile(load_settings().profile).system_prompt


# 兼容旧引用：默认 profile 的提示词
SYSTEM_PROMPT = get_profile("finance").system_prompt


def _build_context(hits, max_chars: int | None = None) -> str:
    """把命中块拼成上下文。每块都包进 <document trust="untrusted">。

    为什么不用纯文本拼接：文档正文里可以写「忽略以上指令」，而模型看到的
    只是一段连续文本，分不清哪句是资料、哪句是命令。加边界 + system 里说明
    「document 内是数据」，是把「可被投毒」降成「可能被投毒且留痕」。

    为什么要截断（C2）：4 块 × 320 字看着不多，但表格与长条款块可以到几千字，
    拼起来能挤掉当前问题本身。超过 `MAX_CONTEXT_CHARS` 就按命中顺序裁掉尾部，
    并在结尾写明「另有 N 段未纳入」——截断必须可见，否则模型以为资料就这些。
    """
    budget = int(max_chars or load_settings().max_context_chars or 6000)
    lines: list[str] = []
    used = 0
    dropped = 0
    for i, (chunk, _score) in enumerate(hits, 1):
        block = injection.wrap(i, chunk.title, chunk.section, chunk.text)
        if lines and used + len(block) > budget:
            dropped += 1
            continue
        lines.append(block)
        used += len(block)
    text = "\n\n".join(lines)
    if dropped:
        text += f"\n\n（资料较长，另有 {dropped} 段未纳入本次上下文）"
    return text


def _best_sentence(query: str, chunk) -> str:
    """在命中块里挑与问题重合最高的句子。

    取「前 2 个高分句」而非只取 1 句：避免两问（如「起购金额+期限」）只答一半，
    也避免并列时因取首句而漏掉关键条款；拼接后保持原顺序，读起来仍连贯。
    """
    q = set(tokenize(query))
    scored: list[tuple[int, int, str]] = []
    for pos, s in enumerate(re.split(r"(?<=[。；;！!？?\n])", chunk.text)):
        s = s.strip()
        if not s:
            continue
        scored.append((len(q & set(tokenize(s))), pos, s))
    if not scored:
        return chunk.text.strip()

    positive = [x for x in scored if x[0] > 0]
    if positive:
        chosen = sorted(positive, key=lambda x: -x[0])[:2]  # 取分数最高的 2 句
    else:
        chosen = scored[:1]
    chosen.sort(key=lambda x: x[1])  # 再按原文顺序拼接
    return "".join(s for _, _, s in chosen).strip()


def extractive_answer(query: str, hits) -> str:
    if not hits:
        return "资料中未找到相关内容。"
    top = hits[0][0]
    sentence = _best_sentence(query, top)
    return f"（离线抽取模式，未调用大模型）根据《{top.title}》·{top.section}：{sentence} [1]"


def chat(
    messages: list[dict],
    temperature: float = 0.0,
    model: str | None = None,
    timeout_s: float | None = None,
) -> tuple[str, dict]:
    """通用 OpenAI 兼容对话调用（生成层与 L3 裁判共用）。

    - 生成层不传 model，走配置里的默认模型；
    - L3 裁判传 model，可用另一个模型做裁判（同一端点即可）。
    显式超时；不在此处重试——重试策略由调用方按场景决定。
    """
    settings = load_settings()
    key = api_key()
    if not key:
        raise RuntimeError("LLM_API_KEY 未配置")
    payload = {
        "model": model or settings.model,
        "messages": messages,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        settings.api_base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s or settings.llm_timeout_s) as resp:
        obj = json.loads(resp.read().decode("utf-8"))
    return obj["choices"][0]["message"]["content"].strip(), obj.get("usage", {})


def repair_citation(query: str, hits, answer: str) -> str | None:
    """补引用：已有答案正确但漏了 [n] 时，先让它补出处，而不是直接丢弃。

    为什么需要：短问题（如「R2 需要双录吗」）模型常给出正确但无标注的回答，
    若直接降级为抽取式，答案反而更差。补引用只允许「加标注 / 删无据句」，
    不允许新增内容，因此不会放松「无出处不交付」这条红线。
    """
    messages = [
        {"role": "system", "content": system_prompt()},
        {
            "role": "user",
            "content": (
                f"【资料】\n{_build_context(hits)}\n\n"
                f"【问题】{query}\n\n"
                f"【已有回答】{answer}\n\n"
                "请为上述【已有回答】补充来源编号标注，要求：\n"
                "1) 只允许两种情况：为已有句子补 [n]；删除资料中找不到依据的句子。\n"
                "2) 严禁新增资料之外的事实、数字或建议。\n"
                "3) 直接输出修订后的回答，不要解释你改了什么。"
            ),
        },
    ]
    text, _usage = chat(messages, temperature=0.0)
    return text.strip() or None


HISTORY_MAX_TURNS = 1        # 只带最近一轮：再多会让模型开始复述旧答案
HISTORY_MAX_CHARS = 240      # 每段截断，避免历史挤掉资料与当前问题


def build_messages(query: str, hits, history=None) -> list[dict]:
    """生成与流式共用同一份提示，避免两条路径的答案口径不一致。

    为什么要带历史：追问「那第二条呢」离开上一轮就无从理解。以前只把历史用于
    改写检索词，模型看不到对话，答案常常答非所问。这里只带**最近一轮**，
    且历史明确标为「仅供参考」——资料才是本次回答的依据。
    """
    messages = [{"role": "system", "content": system_prompt()}]
    for turn in list(history or [])[-HISTORY_MAX_TURNS:]:
        question = str(getattr(turn, "query", "") or "").strip()[:HISTORY_MAX_CHARS]
        answer = str(getattr(turn, "answer", "") or "").strip()[:HISTORY_MAX_CHARS]
        if not question:
            continue
        messages.append({"role": "user", "content": f"（上一轮）{question}"})
        if answer:
            messages.append({"role": "assistant", "content": answer})
    messages.append(
        {"role": "user", "content": f"【资料】\n{_build_context(hits)}\n\n【问题】{query}"})
    return messages


def _call_llm(query: str, hits, model: str | None = None, history=None) -> tuple[str, dict]:
    return chat(build_messages(query, hits, history), temperature=0.1, model=model)


def _stream_budget_s(default: float = 180.0) -> float:
    """流式回答的总时长上限。

    `urlopen(timeout=)` 管的是「socket 空闲多久算超时」，不是「总共能花多久」。
    模型只要每几秒吐一个 token，就能让一次请求拖上十几分钟，占着线程与 SSE 名额。
    这里给整条流一个总预算，超了就抛错、由调用方降级为抽取式。
    """
    raw = (os.environ.get("LLM_STREAM_MAX_S") or "").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def stream_chat(messages: list[dict], temperature: float = 0.1, model: str | None = None,
                timeout_s: float | None = None, usage_out: dict | None = None):
    """OpenAI 兼容的流式对话：逐段 yield 文本增量。

    只在生成层使用：上游一旦开始输出就不再重试（半截答案重试会产生重复内容），
    出错由调用方降级为抽取式并让前端整体替换。
    """
    settings = load_settings()
    key = api_key()
    if not key:
        raise RuntimeError("LLM_API_KEY 未配置")
    payload = {
        "model": model or settings.model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    req = urllib.request.Request(
        settings.api_base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    saw_done = False
    budget = _stream_budget_s()
    deadline = time.monotonic() + budget
    with urllib.request.urlopen(req, timeout=timeout_s or settings.llm_timeout_s) as resp:
        for raw in resp:
            if time.monotonic() > deadline:
                raise RuntimeError(f"流式响应超过 {int(budget)} 秒上限")
            line = raw.decode("utf-8", errors="replace").strip()
            if not line or line.startswith(":") or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                saw_done = True
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if usage_out is not None and isinstance(obj.get("usage"), dict):
                usage_out.update(obj["usage"])
            for choice in obj.get("choices") or []:
                if choice.get("finish_reason"):
                    saw_done = True
                delta = (choice.get("delta") or {}).get("content")
                if delta:
                    yield delta
    if not saw_done:
        # 连接被中途掐断时，半截答案不能当完整答案交付
        raise RuntimeError("流式响应提前结束")


def _is_retryable(exc: Exception) -> bool:
    """只重试幂等的临时性失败；4xx（除 429）重试毫无意义。"""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500 or exc.code == 429
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


def _retry_after(exc: Exception) -> float | None:
    """429 常带 Retry-After（秒）；优先尊重服务端建议，避免无效重试。"""
    if isinstance(exc, urllib.error.HTTPError) and exc.headers is not None:
        raw = exc.headers.get("Retry-After")
        if raw:
            try:
                return float(raw)
            except ValueError:
                return None
    return None


def generate(query: str, hits, model: str | None = None, force_extractive: bool = False,
             history=None) -> dict:
    """生成答案。force_extractive 用于成本上限触发时跳过模型调用。

    `history` 只影响模型能看到的上文（最近一轮），检索与引用校验仍按当前问题。
    """
    settings = load_settings()
    t0 = time.monotonic()

    if force_extractive or not api_key():
        return {
            "mode": "extractive",
            "answer": extractive_answer(query, hits),
            "degraded": False,
            "error": None,
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "usage": {},
        }

    last_err = None
    deadline = t0 + settings.wall_clock_budget_s
    for attempt in range(settings.llm_max_retries + 1):
        if time.monotonic() > deadline:
            last_err = TimeoutError("超出墙钟预算")
            break
        try:
            answer, usage = _call_llm(query, hits, model=model, history=history)
            return {
                "mode": "llm",
                "answer": answer,
                "degraded": False,
                "error": None,
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "usage": usage,
            }
        except Exception as exc:  # noqa: BLE001 —— 先分类再决定
            last_err = exc
            if not _is_retryable(exc) or attempt >= settings.llm_max_retries:
                break
            backoff = min(settings.llm_backoff_max_s, settings.llm_backoff_base_s * (2 ** attempt))
            retry_after = _retry_after(exc)
            wait = max(backoff, retry_after) if retry_after else backoff
            wait = min(wait, max(0.0, deadline - time.monotonic()))  # 不超过墙钟预算
            if wait <= 0:
                break
            time.sleep(wait + random.uniform(0, 0.3))

    # 降级为抽取式，并显式标记 degraded —— 绝不静默失败
    return {
        "mode": "extractive_fallback",
        "answer": extractive_answer(query, hits),
        "degraded": True,
        "error": str(last_err),
        "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        "usage": {},
    }
