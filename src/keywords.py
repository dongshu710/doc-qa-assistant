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

from .config import api_key, load_settings

BUILDER_VERSION = 2

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

    def keys(self) -> list[str]:
        out = [_norm(self.term)] + [_norm(a) for a in self.aliases]
        return [k for k in out if k]

    def to_json(self) -> dict:
        return {
            "term": self.term, "kind": self.kind, "section": self.section,
            "doc": self.doc_id, "snippet": self.snippet, "aliases": list(self.aliases),
            "weight": round(self.weight, 3),
        }


@dataclass
class Hit:
    entry: Entry
    score: float

    def to_json(self) -> dict:
        return {**self.entry.to_json(), "score": round(self.score, 3)}


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
    return [x for x in items if x and len(x) <= 20 and not _looks_like_noise(x)]


# 词首/词尾是虚词时，这个 n-gram 基本不是术语
_FUNC_CHARS = set("的了和与及或是在有为对等中上下我你他这那其之把被从向就也都而但")


def _sentence_for(chunks, term: str):
    for idx, chunk in chunks:
        snippet = _first_sentence_with(chunk.text, term)
        if snippet:
            return snippet, idx
    return None, None


def _label_aliases(label: str) -> list[str]:
    """给「爱吃的食物」这类标签补一个短说法（爱吃），否则「我爱吃什么」命不中。"""
    out = []
    core = re.sub(r"(?:的)?(?:食物|东西|饮品|口味|偏好|习惯|情况|时间|内容|清单|列表)$", "", label)
    core = core.strip(_TRAIL)
    if 2 <= len(core) < len(label):
        out.append(core)
    return out


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
                        clean_label = _clean_term(label)
                        is_list = (len(items) >= 2 and len(value) <= 60
                                   and not re.search(r"[。！？!?；;]", value))
                        if is_list:
                            if clean_label and not _looks_like_noise(clean_label):
                                entries.append(Entry(
                                    term=clean_label, doc_id=doc_id, title=chunk.title,
                                    section=chunk.section, snippet=line_text,
                                    kind="explicit" if explicit_section else "item",
                                    weight=1.0 if explicit_section else 0.95,
                                    aliases=_label_aliases(clean_label), chunk_index=idx,
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
                                entries.append(Entry(
                                    term=clean_label, doc_id=doc_id, title=chunk.title,
                                    section=chunk.section, snippet=line_text,
                                    kind="explicit" if explicit_section else "colon",
                                    weight=1.0 if explicit_section else 0.9,
                                    aliases=_label_aliases(clean_label), chunk_index=idx,
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
                best[key] = entry
            elif entry.weight == best[key].weight:
                best[key].aliases = list(dict.fromkeys(best[key].aliases + entry.aliases))[:4]
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
    def match(self, query: str, limit: int | None = None) -> list[Hit]:
        """只认精确包含（词或同义词），命中才算；不做模糊近似，避免截胡正常检索。"""
        if not self.enabled:
            return []
        q = _norm(query)
        if len(q) < 2:
            return []
        limit = limit or int(getattr(self.settings, "keyword_top_n", 3))
        scored: list[tuple[float, Entry]] = []
        for entry in self.entries:
            if entry.kind not in DIRECT_KINDS:
                continue
            best = 0.0
            for key in entry.keys():
                if len(key) >= 2 and key in q:
                    best = max(best, 1.0 if key == _norm(entry.term) else 0.94)
            if best:
                scored.append((best * entry.weight, entry))
        scored.sort(key=lambda x: (-x[0], -x[1].weight, len(x[1].term)))
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
        return picked

    @staticmethod
    def compose(hits: list[Hit]) -> str:
        if not hits:
            return ""
        lines: list[str] = []
        for hit in hits:
            snippet = _display(hit.entry.snippet)
            if snippet and snippet not in lines:
                lines.append(f"· {snippet}")
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
            "entries": len(self.entries),
            "direct": len(direct),
            "docs": len(self.docs),
            "by_kind": {k: sum(1 for e in self.entries if e.kind == k)
                        for k in ("item", "colon", "explicit", "llm", "heading")},
            "built_at": self.meta.get("built_at"),
            "reused": self.meta.get("reused"),
            "llm_docs": sum(1 for d in self.docs.values() if d.get("llm")),
            "last_error": self.last_error,
        }
