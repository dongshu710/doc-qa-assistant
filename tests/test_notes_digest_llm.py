"""大模型摘要测试：全部用假模型，不联网、不花钱。

重点不是「模型写得好不好」，而是**模型坏掉时保存仍然成功**：
超时、坏 JSON、空摘要、没 Key 都必须回落规则摘要，并且回落要留痕。
"""

from __future__ import annotations

import json
import os
import tempfile

for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY"):
    os.environ.pop(key, None)
os.environ.setdefault("NOTE_HOME", tempfile.mkdtemp(prefix="llm-notes-"))

from src.notes import digest_llm  # noqa: E402
from src.notes.model import NoteError  # noqa: E402
from src.notes.select import Msg  # noqa: E402
from src.notes.service import NoteService  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("PASS  " if cond else "FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))


MESSAGES = [
    Msg("user", "出口退税的退税率按什么标准执行？"),
    Msg("assistant", "根据办法第十二条按 13% 执行。决定由财务部每月 5 日前复核申报表。"),
]

GOOD = {
    "title": "出口退税按 13% 执行",
    "kind": "decision",
    "tags": ["#税务", "出口退税", "税务"],
    "sections": {
        "摘要": "退税率统一按 13% 执行，财务部每月 5 日前复核申报表。",
        "要点": "- 依据办法第十二条\n- 2026-11-01 起执行",
        "决策": "- 财务部每月 5 日前复核",
        "待办": "- [ ] 同步给报关行",
        "参考": "- 这一段不在标准小节里，应被丢弃",
    },
}


def fake(text: str):
    def call(messages, timeout_s=None):
        call.seen = messages
        return text
    call.seen = None
    return call


def main() -> int:
    home = tempfile.mkdtemp(prefix="llm-home-")
    service = NoteService(home, digest_mode="auto")

    # 1) 正常路径
    service.chat_call = fake(json.dumps(GOOD, ensure_ascii=False))
    result = service.save({"messages": [
        {"role": "user", "text": MESSAGES[0].text},
        {"role": "assistant", "text": MESSAGES[1].text},
    ], "hint": {"title": "退税率"}})
    check("模型摘要成功时 digest=llm", result["digest"] == "llm", result["digest"])
    check("成功时不标记回落", result["digest_fallback"] is None, str(result["digest_fallback"]))
    check("标签去重并去掉 # 号", result["tags"] == ["税务", "出口退税"], str(result["tags"]))
    check("非标准小节被丢弃", "参考" not in result["markdown"], result["markdown"][:200])
    check("标准小节进文件", "## 摘要" in result["markdown"] and "## 待办" in result["markdown"])
    check("提示词里带上了对话内容",
          "退税率" in service.chat_call.seen[-1]["content"],
          service.chat_call.seen[-1]["content"][:80])
    note_id = result["id"]
    saved_md = open(result["path"], encoding="utf-8").read()
    check("front matter 记录 digest: llm", "digest: llm" in saved_md)

    # 2) 代码围栏：模型常见输出，剥掉后仍算成功
    fenced = fake("```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```")
    data, meta = digest_llm.digest(MESSAGES, {}, mode="llm", call=fenced)
    check("```json 围栏能被剥掉", meta["engine"] == "llm" and data["title"] == GOOD["title"])

    # 3) 坏 JSON → auto 回落
    service.chat_call = fake("抱歉，我无法完成这个任务。")
    result = service.save({"messages": [{"role": "assistant", "text": "结论：按 13% 执行。"}],
                           "hint": {"title": "回落测试"}})
    check("坏 JSON 回落规则摘要", result["digest"] == "rule", result["digest"])
    check("回落原因可读", result["digest_fallback"] == "invalid_output", str(result["digest_fallback"]))
    check("回落仍写出合法笔记", "## 摘要" in result["markdown"])
    check("front matter 记录 digest_fallback",
          "digest_fallback: invalid_output" in open(result["path"], encoding="utf-8").read())

    # 4) 摘要为空 → 回落
    empty = json.loads(json.dumps(GOOD, ensure_ascii=False))
    empty["sections"]["摘要"] = "   "
    service.chat_call = fake(json.dumps(empty, ensure_ascii=False))
    result = service.save({"messages": [{"role": "assistant", "text": "结论：按 13% 执行。"}],
                           "hint": {"title": "空摘要"}})
    check("摘要为空视为无效输出", result["digest_fallback"] == "invalid_output", str(result["digest_fallback"]))

    # 5) 超时 → 回落
    def timeout_call(messages, timeout_s=None):
        raise TimeoutError("timed out")
    service.chat_call = timeout_call
    result = service.save({"messages": [{"role": "assistant", "text": "结论：按 13% 执行。"}],
                           "hint": {"title": "超时"}})
    check("超时回落并标 timeout", result["digest"] == "rule" and result["digest_fallback"] == "timeout",
          str(result["digest_fallback"]))

    # 6) 网络错误 → 回落
    from urllib.error import URLError

    def net_call(messages, timeout_s=None):
        raise URLError("connection refused")
    service.chat_call = net_call
    result = service.save({"messages": [{"role": "assistant", "text": "结论：按 13% 执行。"}],
                           "hint": {"title": "网络"}})
    check("网络错误回落并标 network", result["digest_fallback"] == "network", str(result["digest_fallback"]))

    # 7) mode=llm 必须成功：失败要抛，不能静默存成规则版
    service.chat_call = fake("不是 JSON")
    try:
        service.save({"messages": [{"role": "assistant", "text": "结论"}],
                      "hint": {"title": "严格模式"}}, digest_mode="llm")
        check("llm 模式失败应报错", False)
    except NoteError as exc:
        check("llm 模式失败给出可读错误并提示替代方案",
              "大模型摘要失败" in str(exc) and "--digest rule" in str(exc), str(exc))

    # 8) 无 Key + auto：不发起任何请求，直接规则
    called = {"n": 0}

    def must_not_call(messages, timeout_s=None):
        called["n"] += 1
        return "{}"

    data, meta = digest_llm.digest(MESSAGES, {}, mode="auto", call=None)
    check("无 Key 时 auto 不报错", meta["engine"] == "rule" and meta["fallback"] == "no_key", str(meta))
    if not digest_llm._has_key():
        try:
            digest_llm.digest(MESSAGES, {}, mode="llm", call=None)
            check("无 Key 时 llm 模式明确报错", False, "应当抛 NoteError")
        except NoteError as exc:
            check("无 Key 时 llm 模式明确报错", "no_key" in str(exc), str(exc))
    else:
        check("（本机配了 Key，跳过无 Key 分支）", True)

    # 9) 字段宽容：非法 kind 回落 qa，缺 title 用 hint，tags 从 hint 补
    sloppy = {"kind": "随便", "sections": {"摘要": "有一句摘要。"}}
    data = digest_llm.parse(json.dumps(sloppy, ensure_ascii=False),
                            {"title": "来自 hint 的标题", "tags": ["甲"]})
    check("非法 kind 回落 qa", data["kind"] == "qa", data["kind"])
    check("缺 title 用 hint", data["title"] == "来自 hint 的标题", data["title"])
    check("缺 tags 用 hint", data["tags"] == ["甲"], str(data["tags"]))

    # 10) 标题清洗：换行、引号、超长
    messy = {"title": '  「带"引号"\n的标题」  ', "sections": {"摘要": "x" * 5}}
    data = digest_llm.parse(json.dumps(messy, ensure_ascii=False))
    check("标题压成单行且去引号", data["title"] == '带"引号" 的标题', repr(data["title"]))
    long_title = {"title": "长" * 400, "sections": {"摘要": "x"}}
    check("标题截到 120 字", len(digest_llm.parse(json.dumps(long_title, ensure_ascii=False))["title"]) == 120)

    # 11) rule 模式完全不走模型
    service.chat_call = must_not_call
    result = service.save({"messages": [{"role": "assistant", "text": "结论：按 13% 执行。"}],
                           "hint": {"title": "规则"}}, digest_mode="rule")
    check("rule 模式一次都不调模型", called["n"] == 0 and result["digest"] == "rule")

    # 12) 两次保存同一段内容仍然去重（摘要引擎不同不影响 hash）
    service.chat_call = fake(json.dumps(GOOD, ensure_ascii=False))
    again = service.save({"messages": [
        {"role": "user", "text": MESSAGES[0].text},
        {"role": "assistant", "text": MESSAGES[1].text},
    ], "hint": {"title": "退税率"}},
        digest_mode="rule")
    check("换引擎重存同一内容仍判定重复", again["duplicate_of"] == note_id,
          str(again["duplicate_of"]))

    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
        return 1
    print("DIGEST LLM OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
