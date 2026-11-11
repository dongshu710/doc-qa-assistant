"""OpenAI 兼容端点：纯函数转换 + 真起服务的端到端。

为什么两层都测：
- 纯函数层（messages→query、分片折算）出错的表现是「内容少一段」，
  端到端只看到答案不对，很难定位；
- 端到端层负责抓「协议形状」——流式少一个空行、错误体字段名不对，
  这些在 SDK 侧只表现为一句无信息的报错。
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import openai_compat as compat  # noqa: E402

FAILED = 0
HOST = "127.0.0.1"


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def test_messages() -> None:
    print("messages → query")
    query, ignored = compat.messages_to_query([
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "第一个问题"},
        {"role": "assistant", "content": "第一个回答"},
        {"role": "user", "content": "稳盈的起购金额是多少"},
    ])
    check("只取最后一条 user（历史不拼进检索问题）",
          query == "稳盈的起购金额是多少", query)
    check("没有多模态 part 时 ignored 为 0", ignored == 0, str(ignored))

    query, ignored = compat.messages_to_query([
        {"role": "user", "content": [
            {"type": "text", "text": "这张图写了什么"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
        ]},
    ])
    check("part 列表里的 text 被取出", query == "这张图写了什么", query)
    check("图片 part 记为忽略（不藏进正文）", ignored == 1, str(ignored))

    for bad, why in (
        ([], "空数组"),
        ([{"role": "user", "content": "   "}], "空内容"),
        ([{"role": "wizard", "content": "x"}], "未知 role"),
        ("不是数组", "非数组"),
    ):
        try:
            compat.messages_to_query(bad)
        except compat.CompatError:
            check(f"{why} 被拒", True)
        else:
            check(f"{why} 被拒", False, repr(bad))


def test_suffix() -> None:
    print("流式分片折算（协议只能追加，不能回退）")
    check("已发内容是新文本前缀时只补差量",
          compat.suffix_for("稳盈系列", "稳盈系列的起购金额是1元") == "的起购金额是1元")
    check("空已发 → 原样返回", compat.suffix_for("", "abc") == "abc")
    check("整段替换时按公共前缀截断",
          compat.suffix_for("答错的旧答案", "答对的旧答案") == "对的旧答案",
          compat.suffix_for("答错的旧答案", "答对的旧答案"))
    check("完全重复不重复发", compat.suffix_for("abc", "abc") == "")


def test_payload() -> None:
    print("结果体 → chat.completion")
    result = {
        "answer": "起购金额为 1 元[1]。", "behavior": "answer", "path": "keyword",
        "citations": [{"ref": 1, "title": "01_要素", "section": "起购", "page": 3,
                       "snippet": "起购金额为 1 元", "doc_id": "01_要素", "chunk_index": 0}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 20, "total_tokens": 140},
        "kb_version": "v0019", "confidence": "high",
    }
    payload = compat.to_chat_completion(result, "jiyi", "req-1")
    check("object 是 chat.completion", payload["object"] == "chat.completion")
    check("正文原样（[n] 编号保留给用户核对）",
          payload["choices"][0]["message"]["content"] == result["answer"])
    check("finish_reason 是 stop（未命中也不是 content_filter）",
          payload["choices"][0]["finish_reason"] == "stop")
    check("引用带页码", payload["citations"][0]["page"] == 3,
          json.dumps(payload["citations"], ensure_ascii=False))
    check("usage 三件套齐全",
          payload["usage"] == result["usage"], str(payload["usage"]))
    check("版本与行为有非标准字段兜底",
          payload["x_kb_version"] == "v0019" and payload["x_behavior"] == "answer")

    no_hit = compat.to_chat_completion({"answer": "无法找到答案。",
                                        "behavior": "no_answer"}, "jiyi")
    check("未命中时 citations 是空数组而不是 None",
          no_hit["citations"] == [], str(no_hit["citations"]))
    check("未命中也不改写正文", no_hit["choices"][0]["message"]["content"] == "无法找到答案。")

    err = compat.CompatError("不支持 tools", code="unsupported_parameter")
    body = err.body()
    check("错误体是 OpenAI 形状（error.message/type/code）",
          body["error"]["message"] == "不支持 tools"
          and body["error"]["type"] == "invalid_request_error"
          and body["error"]["code"] == "unsupported_parameter", json.dumps(body, ensure_ascii=False))


def parse_sse_frames(text: str) -> list[str]:
    out = []
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                out.append(line[5:].strip())
    return out


def main() -> None:
    test_messages()
    test_suffix()
    test_payload()

    tmp = tempfile.mkdtemp(prefix="openai_")
    seed = Path(tmp) / "seed"
    seed.mkdir(parents=True)
    (seed / "产品要素.md").write_text(
        "# 稳盈系列产品要素\n\n## 起购金额\n第1条 稳盈系列产品的起购金额为 1 元。\n"
        "第2条 赎回费按持有期限分档收取。\n", encoding="utf-8")
    env = {
        "KB_DIR": os.path.join(tmp, "kb"),
        "KB_SEED_DIR": str(seed),
        "KEYWORD_INDEX": os.path.join(tmp, "kw.json"),
        "RETRIEVAL": "bm25",
        "QUERY_EXPANSION": "off",
        "MIN_SCORE": "0",
        "KB_APPROVAL": "off",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY", "API_KEYS"):
        os.environ.pop(key, None)

    from src.server import create_server

    httpd, _pipe = create_server(HOST, 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def post(path: str, body: dict, timeout: int = 60):
        req = urllib.request.Request(
            base + path, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")

    def raw_post(path: str, body: dict):
        """要拿错误状态码时用：urlopen 会抛 HTTPError。"""
        req = urllib.request.Request(
            base + path, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    print("HTTP：模型清单")
    with urllib.request.urlopen(base + "/v1/models", timeout=10) as resp:
        models = json.loads(resp.read().decode("utf-8"))
    check("/v1/models 返回 200 并只有一个模型",
          models.get("object") == "list" and len(models.get("data") or []) == 1,
          json.dumps(models, ensure_ascii=False))
    check("模型对象字段符合 OpenAI 形状",
          {"id", "object", "created", "owned_by"} <= set(models["data"][0]))

    print("HTTP：非流式对话")
    status, text = post("/v1/chat/completions", {
        "model": "jiyi",
        "messages": [{"role": "user", "content": "稳盈系列产品的起购金额是多少"}],
    })
    body = json.loads(text)
    content = (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    check("返回 200", status == 200, str(status))
    check("答案含命中内容（1 元）", "1 元" in content, content[:80])
    check("带引用（含 ref/section）",
          bool(body.get("citations")) and "ref" in body["citations"][0],
          json.dumps(body.get("citations"), ensure_ascii=False)[:160])
    check("usage 存在", "usage" in body, str(list(body)))

    print("HTTP：流式对话")
    req = urllib.request.Request(
        base + "/v1/chat/completions",
        data=json.dumps({"model": "jiyi", "stream": True,
                         "messages": [{"role": "user",
                                       "content": "稳盈系列产品的起购金额是多少"}]}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        stream_text = resp.read().decode("utf-8")
    frames = parse_sse_frames(stream_text)
    check("以 data: [DONE] 结束", frames and frames[-1] == "[DONE]", str(frames[-2:])[:120])
    chunks = [json.loads(item) for item in frames if item != "[DONE]"]
    answer = "".join(
        (c.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
        for c in chunks)
    check("首帧带 role=assistant",
          (chunks[0]["choices"][0]["delta"] or {}).get("role") == "assistant",
          json.dumps(chunks[0], ensure_ascii=False)[:120])
    check("增量拼起来等于完整答案并含「1 元」", "1 元" in answer, answer[:80])
    check("末帧 finish_reason=stop",
          (chunks[-1]["choices"][0].get("finish_reason")) == "stop",
          json.dumps(chunks[-1], ensure_ascii=False)[:160])
    check("流式也带 usage（用于记账）",
          isinstance(chunks[-1].get("usage"), dict), json.dumps(chunks[-1])[-90:])

    print("HTTP：错误路径")
    status, text = raw_post("/v1/chat/completions", {
        "messages": [{"role": "user", "content": "x"}], "tools": [{"type": "function"}]})
    detail = json.loads(text).get("error") or {}
    check("带 tools → 400 且 type/code 齐全",
          status == 400 and detail.get("code") == "unsupported_parameter",
          f"{status} {text[:120]}")

    status, text = raw_post("/v1/chat/completions",
                            {"messages": [{"role": "assistant", "content": "x"}]})
    check("没有 user 消息 → 400 missing_user_message",
          status == 400 and json.loads(text)["error"]["code"] == "missing_user_message",
          f"{status} {text[:120]}")

    status, text = raw_post("/v1/chat/completions", {"messages": "x"})
    check("messages 类型错误 → 400 而不是 500", status == 400, f"{status} {text[:80]}")

    httpd.shutdown()
    httpd.server_close()

    print("HTTP：配了 API_KEYS 之后")
    os.environ["API_KEYS"] = "compat-key-1"
    httpd2, _ = create_server(HOST, 0)
    port2 = httpd2.server_address[1]
    threading.Thread(target=httpd2.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port2}/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "x"}]}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=15)
            check("无 Key 被拒", False, "竟然 200")
        except urllib.error.HTTPError as exc:
            detail = (json.loads(exc.read().decode("utf-8")) or {}).get("error") or {}
            check("无 Key → 401 且 type=authentication_error",
                  exc.code == 401 and detail.get("type") == "authentication_error",
                  f"{exc.code} {detail}")

        req = urllib.request.Request(f"http://127.0.0.1:{port2}/v1/models",
                                     headers={"Authorization": "Bearer compat-key-1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            check("带 Key 可读模型清单", resp.status == 200)
    finally:
        httpd2.shutdown()
        httpd2.server_close()

    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    if FAILED:
        print(f"\nOPENAI COMPAT: {FAILED} FAILED")
        raise SystemExit(1)
    print("\nOPENAI COMPAT OK")


if __name__ == "__main__":
    main()
