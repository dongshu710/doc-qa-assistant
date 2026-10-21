"""关键词索引：把文档整理成「条目」，命中后在本地直出，全程不调用任何 API。

两条路径要分清楚：

1. **本地抽取（始终执行）**：从清单、表格行、`标签：值` 与章节标题里抽条目。
   条目自带原文片段（snippet），命中即答，可解释、可复现、零成本。
2. **接入 API 后的整理（可选增强）**：对每份文档做一次「摘要 + 关键词 + 同义说法」，
   用来补「起购 / 起点」「忌口 / 不吃」这类词面差异。模型只提供词，**不提供句子**：
   snippet 一律从原文截取，杜绝把模型编的内容当成文档内容输出。

为什么不让模型直接生成答案：
- 关键词命中是路由判断，错了会把问题带进错误分支，本地规则至少能解释为什么命中；
- 直出要求「说的就是文档里的」，模型改写的句子无法保证这一点；
- 不能因为省一次调用，就换来一个无法追溯的答案。

直出只对**结构化条目**（清单项、表格项、标签值、显式关键词、模型补的词）生效；
章节标题与 TF-IDF 词只用于展示与召回提示，不单独触发直出——否则「风险等级」这类
通用词会把制度类问题全部截胡。

命中之后还有三道闸门（`KEYWORD_GUARD=on` 时生效，可整体关闭做 A/B）：

1. **极性/否定**：条目分正（爱吃/喜欢）、负（不吃/不喜欢/忌口）、中性。
   「我不爱吃香菜」里的「爱吃」处于否定作用域内，不能再拿「爱吃的食物」去答；
   同一族条目（去掉极性的核心词相同）正负并存时，按问句极性只留一侧。
2. **意图**：为什么/怎么/区别/流程这类问法要的是解释，条目罗列答不了，交给检索生成。
3. **单文档**：一次直出只取得分最高的那份文档，避免把不同文档的片段拼成一段答案。
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache

from .config import api_key, load_settings

BUILDER_VERSION = 3

_BULLET = re.compile(r"^\s*(?:[-*·•—]|\d{1,2}[.、)]|[（(]\d{1,2}[)）])\s*")
_COLON = re.compile(r"^([^：:]{1,14})[：:]\s*(.+)$")
_ITEM_SEP = re.compile(r"[、,，/／;；]|\s{2,}")
_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")
_TRAIL = "。；;，,、 \t：:"

# 只有这些类型能触发本地直出；heading / term 只做提示
DIRECT_KINDS = ("item", "colon", "explicit", "llm")

_STOP = {
    "的", "了", "和", "与", "及", "或", "是", "在", "有", "为", "对", "等", "中", "上", "下",
    "我们", "你们", "他们", "这个", "那个", "可以", "需要", "进行", "通过", "相关", "以下",
    "如下", "其中", "以及", "一个", "什么", "怎么", "如何", "哪些", "多少", "是否", "已经",
    "没有", "如果", "因为", "所以", "但是", "并且", "同时", "对于", "关于", "根据", "按照",
    "包括", "例如", "比如", "其他", "以上", "一般", "通常", "主要",
}
# 单字条目容易误触发，除这些有实义的字外不接受
_SINGLE_OK = set("辣甜酸苦咸冷热荤素酒茶糖盐油肉鱼蛋奶")

_NOISE = re.compile(r"^[\d\W_]+$")
# 表格表头不是内容，别把「项目：内容」当成条目
_TABLE_HEAD = {"项目", "名称", "内容", "说明", "序号", "类别", "备注", "字段", "取值", "条件", "标准"}

# ---------- 极性：条目本身是「喜欢」还是「不喜欢」 ----------
# 长标记在前，避免「不喜欢」被「不」抢先匹配后剩一个字的残核
_NEG_MARKERS = (
    "不喜欢", "不爱吃", "不爱喝", "不擅长", "不吃", "不喝", "不去", "不爱",
    "忌口", "禁忌", "禁止", "不得", "不宜", "不能", "不可", "避免", "讨厌", "拒绝",
    "无需", "不用", "不", "没", "无", "非",
)
_POS_MARKERS = ("喜欢", "爱吃", "爱喝", "爱去", "偏爱", "擅长", "推荐", "适合")
# 问句里的否定线索：出现任意一个就认为问的是「负向」那一侧
_Q_NEG = re.compile(r"不|没|别|勿|忌|讨厌|避免|拒绝|无需|不用")
_Q_POS = re.compile(r"喜欢|爱吃|爱喝|偏爱|爱去")
# 否定作用域：命中位置前 3 个字内出现否定词，视为该次出现被否定
_NEG_WINDOW = re.compile(r"[不没别勿忌]|讨厌|避免|拒绝")

# 解释型问法：要的是原因/做法/差异，条目罗列答不了
_EXPLAIN = re.compile(r"为什么|为何|原因|理由|怎么|怎样|如何|区别|差异|对比|流程|步骤")
# 个人偏好类条目的核心词只在第一人称提问时生效：「我喜欢什么音乐」可以，
# 「明天天气」不能因为文档里有一条「讨厌的天气」就被当成在问自己
_FIRST_PERSON = re.compile(r"我|本人|自己|咱")
# 这些核心词太泛，不能当别名，否则「时间」「内容」会把同类条目全部拉出来
_GENERIC_CORE = {"食物", "东西", "饮品", "口味", "偏好", "习惯", "情况",
                 "时间", "内容", "清单", "列表", "地方"}

# 纯度量短语不是实体：「每次 1 小时」「每天 200 元」这类切出来的碎片
_MEASURE = re.compile(
    r"^(?:每次|每天|每周|每月|每年|一般|通常|大约|平均|左右)?\s*"
    r"\d+(?:\.\d+)?\s*(?:小时|分钟|次|天|周|个月|年|元|万元|万|%|杯|公里|米)?$"
)
_MEASURE_PREFIX = re.compile(r"^(?:每次|每天|每周|每月|每年|平均).{0,3}\d")


def _norm(text: str) -> str:
    """NFKC + 去空白与零宽，统一大小写；中英文混排时也能做包含判断。"""
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[\s\u200b-\u200f\u2060\ufeff]+", "", text)


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[ \t]+", " ", text).strip()


def _display(text: str) -> str:
    """展示用：保留原文标点（NFKC 会把「：」变成「:」），只去 Markdown 行首标记。"""
    text = re.sub(r"^[>\s]+", "", text or "")
    text = _BULLET.sub("", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _doc_hash(chunks) -> str:
    h = hashlib.sha1()
    for c in chunks:
        h.update(c.doc_id.encode("utf-8"))
        h.update(b"\x00")
        h.update(c.section.encode("utf-8"))
        h.update(b"\x00")
        h.update(c.text.encode("utf-8"))
        h.update(b"\x01")
    return h.hexdigest()[:16]


@dataclass
class Entry:
    term: str
    doc_id: str
    title: str
    section: str
    snippet: str
    kind: str
    weight: float
    aliases: list[str] = field(default_factory=list)
    chunk_index: int = -1
    self_alias: bool = False   # aliases 中是否含「只在第一人称提问时生效」的核心词

    def keys(self) -> list[str]:
        out = [_norm(self.term)] + [_norm(a) for a in self.aliases]
        return list(dict.fromkeys(k for k in out if k))

    @property
    def polarity(self) -> int:
        return _polarity(self.term)[0]

    @property
    def core(self) -> str:
        return _norm(_polarity(self.term)[1])

    def to_json(self) -> dict:
        return {
            "term": self.term, "kind": self.kind, "section": self.section,
            "doc": self.doc_id, "snippet": self.snippet, "aliases": list(self.aliases),
            "weight": round(self.weight, 3), "polarity": self.polarity,
        }


@dataclass
class Hit:
    entry: Entry
    score: float

    def to_json(self) -> dict:
        return {**self.entry.to_json(), "score": round(self.score, 3)}


@dataclass
class MatchReport:
    """一次匹配的完整结论：命中、被规则挡下的条目、整体闸门。

    `rejected` 只用于解释与观测（为什么没直出），不参与答案生成。
    """
    hits: list[Hit] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    gate: str | None = None   # None | explain_intent


def _looks_like_noise(term: str) -> bool:
    if not term or _NOISE.match(term):
        return True
    if _norm(term) in _STOP:
        return True
    if len(term) == 1 and term not in _SINGLE_OK:
        return True
    return False


def _clean_term(term: str) -> str:
    term = _clean(term).strip(_TRAIL)
    term = re.sub(r"^[「『“\"']|[」』”\"']$", "", term).strip()
    return term


@lru_cache(maxsize=8192)
def _polarity(term: str) -> tuple[int, str]:
    """把条目拆成 (极性, 核心词)：+1 正向，-1 负向，0 中性。

    「不吃的食物」→ (-1, 食物)，「爱吃的食物」→ (+1, 食物)，两者核心相同，
    问句里出现否定时应当只保留负向那条。核心词少于 2 字的不拆，避免「非常」
    被当成「非」+「常」。
    """
    text = _clean_term(term)
    if text.startswith("非常"):  # 「非常喜欢」是加强，不是否定
        return 0, text
    for marker in _NEG_MARKERS:
        if text.startswith(marker):
            core = text[len(marker):].lstrip("的")
            if len(core) >= 2:
                return -1, core
    for marker in _POS_MARKERS:
        if text.startswith(marker):
            core = text[len(marker):].lstrip("的")
            if len(core) >= 2:
                return 1, core
    return 0, text


def _negated_at(text: str, start: int) -> bool:
    """命中位置是否处在否定作用域内（只看前面 3 个字）。"""
    return bool(_NEG_WINDOW.search(text[max(0, start - 3):start]))


def _query_polarity(text: str) -> int:
    """问句整体极性：否定线索优先；「喜欢/爱吃」这类才算正向。"""
    if _Q_NEG.search(text):
        return -1
    if _Q_POS.search(text):
        return 1
    return 0


def _is_measure(term: str) -> bool:
    return bool(_MEASURE.match(term) or _MEASURE_PREFIX.match(term))


def _sentences(text: str) -> list[str]:
    out = [s.strip() for s in _SENT_SPLIT.split(text or "") if s and s.strip()]
    return out


def _first_sentence_with(text: str, term: str) -> str:
    for s in _sentences(text):
        if _norm(term) in _norm(s):
            return s[:160]
    return ""


def _parse_line(raw: str) -> tuple[str | None, str] | None:
    """把一行拆成 (标签, 值)；表格行按单元格合并成「表头：值」。"""
    line = raw.strip()
    if not line:
        return None
    if line.startswith("|"):
        cells = [c.strip() for c in line.strip("|").split("|")]
        cells = [c for c in cells if c and not re.fullmatch(r":?-{2,}:?", c)]
        if len(cells) >= 2:
            return cells[0], "、".join(cells[1:])
        return None
    line = _BULLET.sub("", line)
    if not line:
        return None
    match = _COLON.match(line)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return None, line


def _items_from(value: str) -> list[str]:
    items = [_clean_term(x) for x in _ITEM_SEP.split(value)]
    return [x for x in items if x and len(x) <= 20 and not _looks_like_noise(x)
            and not _is_measure(x)]


# 词首/词尾是虚词时，这个 n-gram 基本不是术语
_FUNC_CHARS = set("的了和与及或是在有为对等中上下我你他这那其之把被从向就也都而但")


def _sentence_for(chunks, term: str):
    for idx, chunk in chunks:
        snippet = _first_sentence_with(chunk.text, term)
        if snippet:
            return snippet, idx
    return None, None


def _label_aliases(label: str) -> tuple[list[str], bool]:
    """给「爱吃的食物」这类标签补短说法，返回（别名, 是否为核心词别名）。

    - 去后缀：「爱吃的食物」→「爱吃」，问「我爱吃什么」能命中；
    - 取核心词：「喜欢的音乐」→「音乐」，问「我喜欢什么音乐」能命中。
      核心词只在第一人称提问时生效（见 `_FIRST_PERSON`），避免「明天天气」
      被「讨厌的天气」截胡。
    """
    out: list[str] = []
    core = re.sub(r"(?:的)?(?:食物|东西|饮品|口味|偏好|习惯|情况|时间|内容|清单|列表)$", "", label)
    core = core.strip(_TRAIL)
    if 2 <= len(core) < len(label):
        out.append(core)
    polarity, obj = _polarity(label)
    if polarity and 2 <= len(obj) <= 12 and obj not in _GENERIC_CORE and obj not in out:
        out.append(obj)
        return out, True
    return out, False


class KeywordIndex:
    """关键词索引：构建、缓存、匹配、文档视图。"""

    def __init__(self, chunks, settings=None, path: str | None = None):
        self.chunks = list(chunks or [])
        self.settings = settings or load_settings()
        self.path = path or self._default_path()
        self.entries: list[Entry] = []
        self.docs: dict[str, dict] = {}
        self.meta: dict = {}
        self.last_error: str | None = None
        self._built = False
        self._key_index: dict[str, list[Entry]] | None = None
        self._max_key = 0

    # ---------- 路径与配置 ----------
    def _default_path(self) -> str:
        configured = getattr(self.settings, "keyword_index", "data/index/keywords.json")
        if os.path.isabs(configured):
            return configured
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(root, configured)

    @property
    def enabled(self) -> bool:
        return (getattr(self.settings, "keyword_mode", "on") or "on").lower() != "off"

    @property
    def llm_mode(self) -> str:
        return (getattr(self.settings, "keyword_llm", "auto") or "auto").lower()

    @property
    def llm_on(self) -> bool:
        mode = self.llm_mode
        if mode == "off":
            return False
        if mode == "on":
            return bool(api_key())
        return bool(api_key())

    @property
    def guard_on(self) -> bool:
        """极性/否定、意图、单文档三道闸门的总开关。"""
        return (getattr(self.settings, "keyword_guard", "on") or "on").lower() != "off"

    @property
    def multi_doc(self) -> bool:
        """一次直出是否允许多份文档（默认否，避免拼盘答案）。"""
        return (getattr(self.settings, "keyword_multi_doc", "off") or "off").lower() == "on"

    # ---------- 构建 ----------
    def ensure(self, enrich: bool = True) -> dict:
        """按语料指纹构建；未变的文档复用摘要与同义词缓存。

        `enrich=False` 只做本地抽取（服务启动时用，避免启动就打模型）；
        上传/重建索引时传 True，才对新增或变更的文档做一次模型整理。
        """
        if self._built:
            return self.describe()
        use_llm = self.llm_on and enrich
        fingerprint = _doc_hash(self.chunks)
        cache = self._load_cache()
        same = cache.get("version") == BUILDER_VERSION
        cached_docs: dict = (cache.get("docs") or {}) if same else {}

        by_doc: dict[str, list] = {}
        for i, chunk in enumerate(self.chunks):
            by_doc.setdefault(chunk.doc_id, []).append((i, chunk))

        docs: dict[str, dict] = {}
        for doc_id, rows in by_doc.items():
            text = "\n".join(c.text for _, c in rows)
            doc = {
                "doc_id": doc_id,
                "title": rows[0][1].title or doc_id,
                "hash": _doc_hash([c for _, c in rows]),
                "summary": "",
                "keywords": [],
                "llm": False,
                "error": None,
            }
            previous = cached_docs.get(doc_id) or {}
            if previous.get("hash") == doc["hash"] and (previous.get("llm") or not use_llm):
                doc.update({k: previous.get(k) for k in ("summary", "keywords", "llm", "error")})
            elif use_llm and text.strip():
                enriched = self._enrich(doc_id, text)
                doc.update(enriched)
            docs[doc_id] = doc

        self.docs = docs
        self.entries = self._build_entries(by_doc, docs)
        self._build_key_index()
        self.meta = {
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fingerprint": fingerprint,
            "model": (getattr(self.settings, "model", "") if use_llm else ""),
            "llm_enabled": use_llm,
            "reused": bool(cached_docs),
        }
        self._built = True
        self._save_cache()
        return self.describe()

    def _build_entries(self, by_doc: dict, docs: dict) -> list[Entry]:
        entries: list[Entry] = []
        for doc_id, rows in by_doc.items():
            doc_meta = docs.get(doc_id) or {}
            # 模型补的词：term -> aliases
            llm_alias: dict[str, list[str]] = {}
            for item in doc_meta.get("keywords") or []:
                term = _clean_term(str(item.get("term") or ""))
                if not term:
                    continue
                aliases = [_clean_term(str(a)) for a in (item.get("aliases") or [])]
                aliases = [a for a in aliases if 1 <= len(a) <= 12 and _norm(a) != _norm(term)]
                llm_alias.setdefault(_norm(term), []).extend(aliases)

            seen_terms: set[str] = set()
            for idx, chunk in rows:
                explicit_section = "关键词" in chunk.section or "标签" in chunk.section
                for raw in chunk.text.splitlines():
                    parsed = _parse_line(raw)
                    if not parsed:
                        continue
                    label, value = parsed
                    if raw.strip().startswith("|") and (_clean(label or "") in _TABLE_HEAD
                                                        or _clean(value) in _TABLE_HEAD):
                        continue
                    line_text = _display(raw)
                    if not line_text:
                        continue
                    if label:
                        items = _items_from(value)
                        raw_items = [_clean_term(x) for x in _ITEM_SEP.split(value)]
                        clean_label = _clean_term(label)
                        # 是否清单要看切分后的原始项数：过滤掉「每次 1 小时」这类度量碎片后
                        # 只剩一项，不能因此把整行降级成单值标签，否则真条目会一起丢掉
                        is_list = (len(raw_items) >= 2 and len(value) <= 60
                                   and not re.search(r"[。！？!?；;]", value))
                        if is_list:
                            if clean_label and not _looks_like_noise(clean_label):
                                label_aliases, self_alias = _label_aliases(clean_label)
                                entries.append(Entry(
                                    term=clean_label, doc_id=doc_id, title=chunk.title,
                                    section=chunk.section, snippet=line_text,
                                    kind="explicit" if explicit_section else "item",
                                    weight=1.0 if explicit_section else 0.95,
                                    aliases=label_aliases, chunk_index=idx,
                                    self_alias=self_alias,
                                ))
                                seen_terms.add(_norm(clean_label))
                            for item in items:
                                entries.append(Entry(
                                    term=item, doc_id=doc_id, title=chunk.title,
                                    section=chunk.section, snippet=line_text,
                                    kind="explicit" if explicit_section else "item",
                                    weight=1.1 if explicit_section else 1.0, chunk_index=idx,
                                ))
                                seen_terms.add(_norm(item))
                            continue
                        # 单值标签：用户问的是「起床时间」，不是「早上 7:30」
                        if 1 <= len(value) <= 40 and not re.search(r"[。！？!?]", value):
                            if clean_label and 1 <= len(clean_label) <= 14 \
                                    and not _looks_like_noise(clean_label):
                                label_aliases, self_alias = _label_aliases(clean_label)
                                entries.append(Entry(
                                    term=clean_label, doc_id=doc_id, title=chunk.title,
                                    section=chunk.section, snippet=line_text,
                                    kind="explicit" if explicit_section else "colon",
                                    weight=1.0 if explicit_section else 0.9,
                                    aliases=label_aliases, chunk_index=idx,
                                    self_alias=self_alias,
                                ))
                                seen_terms.add(_norm(clean_label))
                    elif explicit_section:
                        for item in _items_from(value):
                            entries.append(Entry(
                                term=item, doc_id=doc_id, title=chunk.title,
                                section=chunk.section, snippet=line_text,
                                kind="explicit", weight=1.1, chunk_index=idx,
                            ))
                            seen_terms.add(_norm(item))

                # 章节名：只做提示，不单独触发直出
                section_term = re.sub(r"^[一二三四五六七八九十百零\d]+[、.．)]\s*", "",
                                      _clean_term(chunk.section))
                if section_term and section_term not in ("概述", "前言") and len(section_term) <= 20 \
                        and not _looks_like_noise(section_term) and _norm(section_term) not in seen_terms:
                    snippet = (_sentences(chunk.text) or [chunk.text])[0][:120]
                    entries.append(Entry(
                        term=section_term, doc_id=doc_id, title=chunk.title,
                        section=chunk.section, snippet=snippet, kind="heading",
                        weight=0.35, chunk_index=idx,
                    ))
                    seen_terms.add(_norm(section_term))

            # 模型补的词：能落到原文句子的才收，落不到就丢弃
            for key, aliases in llm_alias.items():
                existing = [e for e in entries if e.doc_id == doc_id and _norm(e.term) == key]
                if existing:
                    for entry in existing:
                        entry.aliases = list(dict.fromkeys(entry.aliases + aliases))[:4]
                    continue
                display = next((str(item.get("term")) for item in doc_meta.get("keywords") or []
                                if _norm(str(item.get("term") or "")) == key), key)
                for idx, chunk in rows:
                    snippet = _first_sentence_with(chunk.text, display)
                    if not snippet:
                        continue
                    entries.append(Entry(
                        term=_clean_term(display), doc_id=doc_id, title=chunk.title,
                        section=chunk.section, snippet=snippet, kind="llm",
                        weight=0.8, aliases=aliases[:4], chunk_index=idx,
                    ))
                    seen_terms.add(key)
                    break

        # 同 doc 同词去重，保留权重最高的条目
        best: dict[tuple[str, str], Entry] = {}
        for entry in entries:
            key = (entry.doc_id, _norm(entry.term))
            if key not in best or entry.weight > best[key].weight:
                if key in best:
                    entry.aliases = list(dict.fromkeys(entry.aliases + best[key].aliases))[:4]
                    entry.self_alias = entry.self_alias or best[key].self_alias
                best[key] = entry
            elif entry.weight == best[key].weight:
                best[key].aliases = list(dict.fromkeys(best[key].aliases + entry.aliases))[:4]
                best[key].self_alias = best[key].self_alias or entry.self_alias
        out = sorted(best.values(), key=lambda e: (-e.weight, e.doc_id, e.term))
        return out

    # ---------- 可选：接 API 做整理 ----------
    def _enrich(self, doc_id: str, text: str) -> dict:
        """调用一次模型做摘要与同义词；失败只记录，不影响本地关键词。"""
        from .generator import chat

        limit = int(getattr(self.settings, "keyword_llm_max_chars", 2400))
        body = text[:max(400, limit)]
        messages = [
            {"role": "system", "content": "你是文档整理助手，只输出 JSON，不要解释、不要 Markdown 代码块。"},
            {"role": "user", "content": (
                "阅读文档，输出 JSON："
                '{"summary":"不超过 60 字的文档主题","keywords":[{"term":"原文中出现过的名词或短语",'
                '"aliases":["同义说法"]}]}\n'
                "要求：term 必须在原文出现；keywords 6~16 个；aliases 最多 3 个，每个不超过 8 字；"
                "不要输出整句，不要编造原文没有的事实。\n\n文档：\n" + body
            )},
        ]
        timeout = min(20.0, float(getattr(self.settings, "llm_timeout_s", 30.0)))
        last_error = None
        for attempt in range(2):  # 一次重试足够：建索引不该阻塞上传
            try:
                answer, usage = chat(messages, temperature=0.0, timeout_s=timeout)
                parsed = self._parse_json(answer)
                keywords = self._validate_keywords(parsed.get("keywords"), body)
                summary = _clean(str(parsed.get("summary") or ""))[:120]
                if not keywords:
                    raise ValueError("模型未给出可用关键词")
                return {"summary": summary, "keywords": keywords, "llm": True,
                        "error": None, "usage": usage}
            except Exception as exc:  # noqa: BLE001 —— 增强失败必须退回本地结果
                last_error = f"{type(exc).__name__}: {exc}"[:200]
                if attempt == 0:
                    time.sleep(0.4 + random.uniform(0, 0.4))
        self.last_error = f"{doc_id}: {last_error}"
        return {"summary": "", "keywords": [], "llm": False, "error": last_error}

    @staticmethod
    def _parse_json(text: str) -> dict:
        raw = (text or "").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S).strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("响应中没有 JSON")
        data = json.loads(raw[start:end + 1])
        if not isinstance(data, dict):
            raise ValueError("JSON 顶层不是对象")
        return data

    @staticmethod
    def _validate_keywords(items, body: str) -> list[dict]:
        """只接受原文出现过的 term；同义词可以不在原文，但长度受限。"""
        norm_body = _norm(body)
        out: list[dict] = []
        seen: set[str] = set()
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            term = _clean_term(str(item.get("term") or ""))
            if not (2 <= len(term) <= 12) or _looks_like_noise(term):
                continue
            key = _norm(term)
            if key in seen or key not in norm_body:
                continue
            aliases = []
            for alias in item.get("aliases") or []:
                alias = _clean_term(str(alias))
                if 1 <= len(alias) <= 8 and _norm(alias) != key and not _looks_like_noise(alias):
                    aliases.append(alias)
            seen.add(key)
            out.append({"term": term, "aliases": list(dict.fromkeys(aliases))[:3]})
            if len(out) >= 16:
                break
        return out

    # ---------- 缓存 ----------
    def _load_cache(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        payload = {
            "version": BUILDER_VERSION,
            "built_at": self.meta.get("built_at"),
            "fingerprint": self.meta.get("fingerprint"),
            "model": self.meta.get("model"),
            "llm_enabled": self.meta.get("llm_enabled"),
            "docs": self.docs,
        }
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError as exc:
            self.last_error = f"关键词索引写入失败: {exc}"

    # ---------- 匹配与输出 ----------
    def _build_key_index(self) -> None:
        """key -> 条目 的倒排表：匹配时枚举问句子串，而不是逐个条目做包含判断。"""
        index: dict[str, list[Entry]] = {}
        for entry in self.entries:
            if entry.kind not in DIRECT_KINDS:
                continue
            for key in entry.keys():
                if len(key) >= 2:
                    index.setdefault(key, []).append(entry)
        self._key_index = index
        self._max_key = max((len(k) for k in index), default=0)

    def _scan(self, q: str) -> tuple[list[tuple[float, Entry]], set[str]]:
        """扫一遍问句，返回（候选, 因否定被挡下的词）。候选按条目去重取最高分。"""
        if self._key_index is None:
            self._build_key_index()
        index = self._key_index or {}
        found: dict[str, list[int]] = {}
        max_len = min(self._max_key, len(q))
        for i in range(len(q)):
            for size in range(2, max_len + 1):
                sub = q[i:i + size]
                if sub in index:
                    found.setdefault(sub, []).append(i)

        guard = self.guard_on
        first_person = bool(_FIRST_PERSON.search(q)) if guard else True
        best: dict[int, tuple[float, Entry]] = {}
        negated_terms: set[str] = set()
        for key, positions in found.items():
            # 同一个词出现多次，只要有一处不在否定域内，就算真的命中
            neg_all = guard and all(_negated_at(q, p) for p in positions)
            for entry in index[key]:
                # 核心词别名只在第一人称提问时成立，避免把别人的偏好当成通用知识
                if entry.self_alias and not first_person and key == entry.core:
                    continue
                if entry.polarity > 0 and neg_all:
                    negated_terms.add(entry.term)
                    continue
                score = (1.0 if key == _norm(entry.term) else 0.94) * entry.weight
                slot = best.get(id(entry))
                if slot is None or score > slot[0]:
                    best[id(entry)] = (score, entry)
                negated_terms.discard(entry.term)
        return list(best.values()), negated_terms

    def match_report(self, query: str, limit: int | None = None) -> MatchReport:
        """只认精确包含（词或同义词），再依次过极性、意图、单文档三道闸门。"""
        if not self.enabled:
            return MatchReport()
        q = _norm(query)
        if len(q) < 2:
            return MatchReport()
        limit = limit or int(getattr(self.settings, "keyword_top_n", 3))

        # 闸门一：解释型问法。先扫一遍，确认本来会命中才记闸门——
        # 否则「今天天气怎么样」也会被记成「被意图挡下」，指标就失真了
        scored, negated_terms = self._scan(q)
        if self.guard_on and _EXPLAIN.search(q) and scored:
            return MatchReport(gate="explain_intent")

        rejected: list[dict] = []
        if self.guard_on and scored:
            hit_terms = {entry.term for _, entry in scored}
            for term in sorted(negated_terms - hit_terms):
                rejected.append({"term": term, "reason": "negated"})

            # 闸门二：同族正负并存时，按问句极性只留一侧
            q_pol = _query_polarity(q)
            if q_pol:
                families: dict[tuple[str, str], list[Entry]] = {}
                for _, entry in scored:
                    if entry.core:
                        families.setdefault((entry.doc_id, entry.core), []).append(entry)
                drop: set[int] = set()
                for entries in families.values():
                    pols = {e.polarity for e in entries}
                    if q_pol < 0 and -1 in pols:
                        # 问的是「不喜欢/不吃」，同族的中性条目与正向条目都不该出现：
                        # 「我不喜欢的运动」不能被「运动：每周三次游泳」答成喜欢的事
                        drop.update(id(e) for e in entries if e.polarity != -1)
                    elif q_pol > 0 and -1 in pols:
                        # 问的是「喜欢/爱吃」，负向条目要挡掉；中性条目仍可能是答案
                        drop.update(id(e) for e in entries if e.polarity == -1)
                if drop:
                    kept = []
                    for score, entry in scored:
                        if id(entry) in drop:
                            rejected.append({"term": entry.term, "reason": "polarity_conflict"})
                        else:
                            kept.append((score, entry))
                    scored = kept

        scored.sort(key=lambda x: (-x[0], -x[1].weight, len(x[1].term)))

        # 闸门三：一次直出只取得分最高的文档，避免把不同文档的片段拼成一段答案
        if self.guard_on and not self.multi_doc and scored:
            doc_score: dict[str, float] = {}
            doc_count: dict[str, int] = {}
            first: dict[str, int] = {}
            for pos, (score, entry) in enumerate(scored):
                doc_score[entry.doc_id] = doc_score.get(entry.doc_id, 0.0) + score
                doc_count[entry.doc_id] = doc_count.get(entry.doc_id, 0) + 1
                first.setdefault(entry.doc_id, pos)
            best_doc = max(doc_score, key=lambda d: (doc_score[d], doc_count[d], -first[d]))
            kept = []
            for score, entry in scored:
                if entry.doc_id != best_doc:
                    rejected.append({"term": entry.term, "reason": "other_doc"})
                else:
                    kept.append((score, entry))
            scored = kept

        picked: list[Hit] = []
        seen: set[tuple[str, str, str]] = set()
        for score, entry in scored:
            key = (entry.doc_id, entry.section, entry.snippet)
            if key in seen:
                continue
            seen.add(key)
            picked.append(Hit(entry=entry, score=min(1.0, score)))
            if len(picked) >= limit:
                break
        return MatchReport(hits=picked, rejected=rejected[:12])

    def match(self, query: str, limit: int | None = None) -> list[Hit]:
        return self.match_report(query, limit).hits

    @staticmethod
    def merge(hits: list[Hit]) -> list[Hit]:
        """按（文档, 章节, 原文）去重：一条原文只留一次，引用编号才不会错位。"""
        out: list[Hit] = []
        seen: set[tuple[str, str, str]] = set()
        for hit in hits:
            if not _display(hit.entry.snippet):
                continue
            key = (hit.entry.doc_id, hit.entry.section, hit.entry.snippet)
            if key in seen:
                continue
            seen.add(key)
            out.append(hit)
        return out

    @staticmethod
    def compose(hits: list[Hit]) -> str:
        if not hits:
            return ""
        multi = len(hits) > 1
        lines: list[str] = []
        seen: set[str] = set()
        for i, hit in enumerate(hits, 1):
            snippet = _display(hit.entry.snippet)
            if not snippet or snippet in seen:
                continue
            seen.add(snippet)
            lines.append(f"· {snippet}" + (f" [{i}]" if multi else ""))
        return "\n".join(lines)

    # ---------- 视图 ----------
    def top_terms(self, doc_id: str, n: int = 6) -> list[str]:
        primary = [e for e in self.entries if e.doc_id == doc_id and e.kind != "heading"]
        rows = list(primary)
        if len(rows) < 3:  # 没有清单的文档，用章节名兜底，避免展示空关键词
            rows += [e for e in self.entries if e.doc_id == doc_id and e.kind == "heading"]
        rows.sort(key=lambda e: (-e.weight, len(e.term)))
        out: list[str] = []
        for entry in rows:
            if entry.term not in out:
                out.append(entry.term)
            if len(out) >= n:
                break
        return out

    def doc_view(self, doc_id: str) -> dict:
        doc = self.docs.get(doc_id) or {}
        rows = [e for e in self.entries if e.doc_id == doc_id]
        rows.sort(key=lambda e: (-e.weight, e.section, e.term))
        return {
            "doc_id": doc_id,
            "title": doc.get("title") or doc_id,
            "summary": doc.get("summary") or "",
            "llm": bool(doc.get("llm")),
            "error": doc.get("error"),
            "terms": [e.to_json() for e in rows[:200]],
            "count": len(rows),
        }

    def summary(self) -> dict:
        direct = [e for e in self.entries if e.kind in DIRECT_KINDS]
        return {
            "enabled": self.enabled,
            "llm": self.llm_on,
            "guard": self.guard_on,
            "multi_doc": self.multi_doc,
            "docs": len({e.doc_id for e in self.entries}),
            "terms": len(self.entries),
            "direct": len(direct),
            "by_doc": {doc_id: self.top_terms(doc_id, 6) for doc_id in self.docs},
        }

    def describe(self) -> dict:
        direct = [e for e in self.entries if e.kind in DIRECT_KINDS]
        return {
            "enabled": self.enabled,
            "llm": self.llm_on,
            "guard": self.guard_on,
            "multi_doc": self.multi_doc,
            "entries": len(self.entries),
            "direct": len(direct),
            "docs": len(self.docs),
            "by_kind": {k: sum(1 for e in self.entries if e.kind == k)
                        for k in ("item", "colon", "explicit", "llm", "heading")},
            "by_polarity": {
                "positive": sum(1 for e in direct if e.polarity > 0),
                "negative": sum(1 for e in direct if e.polarity < 0),
                "neutral": sum(1 for e in direct if e.polarity == 0),
            },
            "built_at": self.meta.get("built_at"),
            "reused": self.meta.get("reused"),
            "llm_docs": sum(1 for d in self.docs.values() if d.get("llm")),
            "last_error": self.last_error,
        }
