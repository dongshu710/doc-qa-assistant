"""查询扩展：把用户口语化问题改写成「贴合知识库术语」的检索关键词串。

为什么不用同义词表：同义词表是**领域绑定**的（R1-R5、双录、起购……），
一旦换成通用文档问答就失效。这里改成**语料自适应**：
把知识库的章节标题作为词表一起给模型，让它用文档自己的术语改写，
既领域无关，又能解决「R3/R5 被当成相机型号」这类跨领域歧义。

代价与取舍：
- 每题多一次短调用（10~25s 波动较大），所以默认 `QUERY_EXPANSION=auto`：有 Key 才启用；
- 失败或超时**静默回退原问题**，扩展只是加分项，不能成为新的故障点；
- 结果做进程内缓存，评测/重复提问不重复花钱。
"""
import time

from .config import api_key
from .generator import chat

EXPAND_SYSTEM = """你是文档检索的查询改写器。用户会给出【知识库章节列表】和【问题】。

任务：把问题改写成一行检索关键词，要求：
1) 优先复用章节列表里的术语（这是同一份文档的正式说法）；
2) 补全问题里省略、但检索时需要的限定词；
3) 只输出一行关键词，空格分隔，不要编号、不要解释、不要回答问题；
4) 不超过 40 个字。

示例：
章节：三、产品风险等级与适当性匹配 / 二、客户风险承受能力评估
问题：我是 R3 想买 R5 行不行
输出：风险承受能力等级 产品风险等级 适当性匹配 不匹配确认书"""

_CACHE: dict[str, str] = {}
_MAX_CACHE = 500
LAST_ERROR: str | None = None


def _clean(text: str) -> str:
    """只保留第一行有效内容，去掉编号/项目符号。"""
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-*•0123456789.、) ").strip()
        if line:
            return line[:80]
    return ""


def expand(query: str, vocabulary: list[str] | None = None,
           timeout_s: float | None = None) -> tuple[str, bool]:
    """返回 (用于检索的查询串, 是否真正扩展过)。任何异常都回退原文。"""
    global LAST_ERROR
    q = (query or "").strip()
    if len(q) < 4 or not api_key():
        return q, False
    vocab_key = "|".join((vocabulary or [])[:5])
    cache_key = q + "##" + vocab_key
    if cache_key in _CACHE:
        return _CACHE[cache_key], _CACHE[cache_key] != q

    user = f"【知识库章节】{' / '.join(vocabulary or []) or '（无）'}\n【问题】{q}"
    text = None
    for attempt in range(2):   # 偶发超时/429 很常见，重试一次再放弃
        try:
            text, _usage = chat(
                [{"role": "system", "content": EXPAND_SYSTEM}, {"role": "user", "content": user}],
                temperature=0.0,
                timeout_s=timeout_s,
            )
            break
        except Exception as exc:  # noqa: BLE001 —— 扩展失败不影响主链路
            LAST_ERROR = str(exc)
            if attempt == 0:
                time.sleep(2.0)
    if text is None:
        return q, False

    extra = _clean(text)
    if not extra or extra in q:
        return q, False
    combined = f"{q} {extra}"
    if len(_CACHE) < _MAX_CACHE:
        _CACHE[cache_key] = combined
    return combined, True
