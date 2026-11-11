"""OpenAI 兼容层：`/v1/models` 与 `/v1/chat/completions`。

为什么单独一层，而不是让 handler 直接拼 JSON：
- 转换规则（messages → query、引用 → 附加字段、流式分片）是纯函数，
  可以在没有 HTTP、没有模型的情况下逐条断言；放 handler 里就只能起服务测。
- OpenAI 协议的错误体与主协议（`{ok, error, message}`）形状不同。
  混在一起最典型的后果是：SDK 拿到 400 却只显示「unexpected response」，
  真正的「messages 里没有 user」被吃掉。

边界（不假装兼容的部分）：
- 只支持 `messages` 里的 `content` 字符串，或 `[{type:"text",text:"..."}]` 列表；
  图片等其它 part 直接忽略并在 usage 之外的 `x_ignored_parts` 里标出来。
- 不支持 `tools` / `function_call`：本项目是「只依据资料作答」的工作流，
  接了工具调用就等于变成 Agent，与定位冲突（见 README）。
- `n>1` 不支持：一次检索只有一份证据，给两个答案会让引用编号对不上。
"""
from __future__ import annotations

import json
import time
import uuid

# 请求体里我们认得但不支持的字段。显式列出来拒绝，比静默忽略安全：
# 用户设了 tools 却拿到一个不调工具的答案，会以为「模型不听话」，实际是没实现。
UNSUPPORTED = ("tools", "tool_choice", "functions", "function_call")


class CompatError(ValueError):
    """协议层错误：带上 HTTP 状态与 OpenAI 的 error.type。"""

    def __init__(self, message: str, status: int = 400, kind: str = "invalid_request_error",
                 code: str = "invalid_request"):
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.code = code

    def body(self) -> dict:
        return {"error": {"message": str(self), "type": self.kind, "code": self.code}}


def _text_of(content) -> tuple[str, int]:
    """取一条消息的文本，返回 (文本, 被忽略的 part 数)。

    `content` 允许两种形状：字符串（最常见）与 part 列表（新版 SDK 发多模态时用）。
    多模态里除 text 之外一律忽略——本项目没有视觉模型，硬塞进去只会让下游把
    `[image_url]` 当成正文检索。
    """
    if isinstance(content, str):
        return content, 0
    if isinstance(content, list):
        parts: list[str] = []
        ignored = 0
        for item in content:
            if isinstance(item, dict) and item.get("type") in (None, "text"):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                else:
                    ignored += 1
            elif isinstance(item, str):
                parts.append(item)
            else:
                ignored += 1
        return "\n".join(parts), ignored
    return "", 1 if content is not None else 0


def messages_to_query(messages) -> tuple[str, int]:
    """把 messages 压成一个检索问题，返回 (query, 被忽略的 part 数)。

    只取**最后一条 user**：检索是「按一个问题找证据」，把整段历史拼进去会让
    向量偏离当前问题（实测追问场景下 top-1 会掉到上一轮的主题）。
    历史本来也不该由这里维护——多轮上下文由 `session_id` 与磁盘会话负责，
    这里传历史是为了兼容客户端习惯，不是为了让模型读它。
    """
    if not isinstance(messages, list) or not messages:
        raise CompatError("messages 必须是非空数组")
    ignored = 0
    last_user = ""
    for item in messages:
        if not isinstance(item, dict):
            raise CompatError("messages 的每一项必须是对象")
        role = str(item.get("role") or "")
        if role not in ("system", "user", "assistant", "tool", "developer"):
            raise CompatError(f"不支持的 role：{role!r}", code="invalid_role")
        if role in ("user", "developer"):
            text, skipped = _text_of(item.get("content"))
            ignored += skipped
            if text.strip():
                last_user = text
    if not last_user.strip():
        raise CompatError("messages 里没有可用的 user 内容", code="missing_user_message")
    return last_user.strip()[:4000], ignored


def models_payload(model: str, created: int | None = None) -> dict:
    """`GET /v1/models`：只报一个模型名。

    报一个而不是列一串：这里没有「模型列表」这个概念——模型由 `LLM_MODEL`
    决定，写多个会让 SDK 在启动时随机挑一个，然后因为名字对不上而报错。
    """
    stamp = int(created if created is not None else time.time())
    return {
        "object": "list",
        "data": [{"id": model or "jiyi", "object": "model", "created": stamp,
                  "owned_by": "local"}],
    }


def _citations(result: dict) -> list[dict]:
    """挑出对外该暴露的引用字段：页码、章节、片段，以及版本。"""
    out: list[dict] = []
    for item in result.get("citations") or []:
        if not isinstance(item, dict):
            continue
        out.append({
            "ref": item.get("ref"),
            "title": item.get("title") or item.get("doc_id") or "",
            "section": item.get("section") or "",
            # page 只有 PDF 入库才有；None 表示这份文档没有页概念（md/docx/xlsx）
            "page": item.get("page"),
            "snippet": item.get("snippet") or "",
            "doc_id": item.get("doc_id") or "",
            "chunk_index": item.get("chunk_index"),
        })
    return out


def usage_of(result: dict) -> dict:
    usage = result.get("usage") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def completion_id() -> str:
    return "chatcmpl-" + uuid.uuid4().hex[:24]


def to_chat_completion(result: dict, model: str, request_id: str = "") -> dict:
    """把本项目的结果体翻译成 `chat.completion`。

    `finish_reason`：未命中（no_answer）与拒答（refuse）都算正常结束（stop），
    不用 `content_filter`——那会让客户端以为答案被平台审查掉了，而实际是
    「资料里没有」或「问题不该答」。真实原因放在 `x_behavior` 里。
    """
    behavior = str(result.get("behavior") or "")
    answer = str(result.get("answer") or "")
    payload = {
        "id": completion_id(),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or "jiyi",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": answer},
            "finish_reason": "stop",
            "logprobs": None,
        }],
        "usage": usage_of(result),
        # 以下为非标准字段：OpenAI SDK 会原样保留在响应对象里，别的客户端忽略即可。
        # 引用放在这里而不是拼进正文，是因为正文要能直接拿去展示；
        # 拼进去会把 [n] 的语义（能不能核对）和排版混在一起。
        "citations": _citations(result),
        "x_behavior": behavior,
        "x_path": result.get("path") or "",
        "x_confidence": result.get("confidence") or "",
        "x_kb_version": result.get("kb_version"),
    }
    if result.get("similar_questions"):
        payload["x_similar_questions"] = result["similar_questions"]
    if request_id:
        payload["x_request_id"] = request_id
    return payload


def to_sse_chunk(text: str, model: str, completion: str, created: int,
                 finish: str | None = None, role: bool = False,
                 usage: dict | None = None) -> str:
    """一条 `chat.completion.chunk`。返回已经带 `data: ` 前缀与空行的整帧。

    为什么要拼成整帧：调用方只要 `write()` 一次，不必在每个发送点都记住
    「两行换行 + data 前缀」——漏一个空行，SDK 就永远等不到这段。
    """
    delta: dict = {}
    if role:
        delta["role"] = "assistant"
    if text:
        delta["content"] = text
    body = {
        "id": completion,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model or "jiyi",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish, "logprobs": None}],
    }
    if usage is not None:
        # 非标准：OpenAI 只在 stream_options.include_usage 时给，但它们不排斥多给。
        # 客户端据此能算成本，否则流式调用在账单一栏永远是空的。
        body["usage"] = usage
    return "data: " + json.dumps(body, ensure_ascii=False) + "\n\n"


def error_frame(message: str, kind: str = "server_error",
                code: str = "internal_error") -> str:
    """流开始之后才发生的错误：只能用一帧数据告诉客户端。

    不能用 HTTP 状态码——响应头早就发出去了。这时候沉默关闭连接是最坏的选择：
    SDK 只会报「连接中断」，用户拿不到任何原因。
    """
    body = {"error": {"message": message, "type": kind, "code": code}}
    return "data: " + json.dumps(body, ensure_ascii=False) + "\n\n"


def sse_done() -> str:
    return "data: [DONE]\n\n"


def suffix_for(sent: str, new: str) -> str:
    """算出「还需要追加哪一段」。

    流式里上游会发两种事件：增量（delta）与整段替换（replace，出现在生成被
    重排或降级时）。OpenAI 协议只能追加，不能回退，所以：
    - 新文本以已发送内容开头 → 追加剩余部分（正常情况）；
    - 否则按最长公共前缀截断，只补后缀。极端情况下客户端会看到重复的尾字，
      但这比「整段丢弃」或「沉默到结束」更接近真实答案。
    """
    if not sent:
        return new
    if new.startswith(sent):
        return new[len(sent):]
    limit = min(len(sent), len(new))
    index = 0
    while index < limit and sent[index] == new[index]:
        index += 1
    return new[index:]
