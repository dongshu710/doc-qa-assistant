"""离线导出：把笔记打成一个自包含的 HTML（或 JSON bundle）。

为什么要单文件：用户可能把笔记拷到没有本服务、甚至没有网络的机器上看。
所以这里不引任何外部 CSS/字体/脚本，图片也不外链——打开就能读，断网也能读。
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

BUNDLE_SCHEMA = "notes-bundle/v1"
_URL = re.compile(r"(https?://[^\s<>\"']+)")

EXPORT_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1a2233;--muted:#5a6478;--line:#e3e7ee;--accent:#2f5bd7;--tag:#eef2fb}
@media (prefers-color-scheme:dark){
  :root{--bg:#12151c;--card:#1a1f29;--ink:#e7ebf3;--muted:#9aa5b8;--line:#2a3140;--accent:#8fb0ff;--tag:#232b3a}
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);
  padding:18px 20px 12px}
h1{margin:0 0 4px;font-size:19px}
.meta{color:var(--muted);font-size:13px}
.bar{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap}
.bar input{flex:1 1 220px;min-width:0;padding:8px 11px;border:1px solid var(--line);border-radius:8px;
  background:var(--card);color:var(--ink);font-size:14px}
.bar select{padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);
  color:var(--ink);font-size:14px}
main{max-width:820px;margin:0 auto;padding:18px 20px 60px}
.note{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;
  margin:0 0 16px}
.note h2{margin:0 0 6px;font-size:17px;line-height:1.4}
.note .meta{margin-bottom:10px}
.tag{display:inline-block;background:var(--tag);color:var(--accent);border-radius:999px;
  padding:1px 8px;font-size:12px;margin-right:6px}
.note h3{margin:14px 0 4px;font-size:13px;color:var(--muted);font-weight:600;letter-spacing:.04em}
.note p{margin:4px 0}
.note ul{margin:4px 0;padding-left:20px}
.note code{background:var(--tag);border-radius:4px;padding:1px 4px;font-size:13px}
.note a{color:var(--accent)}
.empty{color:var(--muted);text-align:center;padding:40px 0}
footer{color:var(--muted);font-size:12px;text-align:center;padding:0 20px 40px}
@media print{header{position:static}.bar{display:none}.note{break-inside:avoid;border-color:#ddd}}
"""

EXPORT_JS = """
(function(){
  var q=document.getElementById('q'), kind=document.getElementById('kind'), notes=[].slice.call(document.querySelectorAll('.note'));
  function apply(){
    var text=(q.value||'').trim().toLowerCase(), k=kind.value;
    var shown=0;
    notes.forEach(function(n){
      var okText=!text||(n.dataset.hay||'').indexOf(text)>=0;
      var okKind=!k||n.dataset.kind===k;
      var on=okText&&okKind;
      n.style.display=on?'':'none';
      if(on) shown++;
    });
    document.getElementById('empty').style.display=shown?'none':'';
    document.getElementById('shown').textContent=shown;
  }
  q.addEventListener('input',apply); kind.addEventListener('change',apply); apply();
})();
"""


def _inline(text: str) -> str:
    """先转义再加链接：不能让正文里的尖括号变成标签。"""
    escaped = html.escape(text, quote=False)
    escaped = _URL.sub(lambda m: f'<a href="{html.escape(m.group(1), quote=True)}">{m.group(1)}</a>', escaped)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)


def _body(text: str) -> str:
    lines = [line.rstrip() for line in (text or "").splitlines()]
    blocks: list[str] = []
    bullets: list[str] = []

    def flush() -> None:
        if bullets:
            blocks.append("<ul>" + "".join(f"<li>{_inline(item)}</li>" for item in bullets) + "</ul>")
            bullets.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith(("- ", "* ")):
            bullets.append(stripped[2:].strip())
            continue
        flush()
        blocks.append(f"<p>{_inline(stripped)}</p>")
    flush()
    return "".join(blocks)


def render_html(notes: list[dict], title: str = "我的笔记", generated_at: str | None = None) -> str:
    stamp = generated_at or datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    cards: list[str] = []
    kinds: dict[str, str] = {"decision": "决策", "howto": "做法", "reference": "资料", "qa": "问答", "log": "记录"}
    for note in notes:
        sections = note.get("sections") or []
        body = "".join(
            f"<h3>{html.escape(str(item.get('title') or ''))}</h3>{_body(str(item.get('body') or ''))}"
            for item in sections
        )
        tags = "".join(f'<span class="tag">{html.escape(str(tag))}</span>' for tag in (note.get("tags") or []))
        hay = " ".join([str(note.get("title") or ""), " ".join(note.get("tags") or []),
                        " ".join(str(item.get("body") or "") for item in sections)]).lower()
        kind = str(note.get("kind") or "qa")
        cards.append(
            f'<article class="note" data-kind="{html.escape(kind)}" data-hay="{html.escape(hay, quote=True)}">'
            f'<h2>{html.escape(str(note.get("title") or "未命名"))}</h2>'
            f'<div class="meta">{html.escape(str(note.get("created") or "")[:10])} · '
            f'{html.escape(kinds.get(kind, kind))} · {html.escape(str(note.get("id") or ""))}'
            f'{" · " + tags if tags else ""}</div>{body}</article>'
        )
    options = "".join(f'<option value="{key}">{label}</option>' for key, label in kinds.items())
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{html.escape(title)}</title><style>{EXPORT_CSS}</style></head><body>
<header>
  <h1>{html.escape(title)}</h1>
  <div class="meta">共 {len(notes)} 篇 · 导出于 {html.escape(stamp)} · 当前显示 <span id="shown">{len(notes)}</span> 篇</div>
  <div class="bar">
    <input id="q" type="search" placeholder="搜索标题、正文或标签" aria-label="搜索笔记">
    <select id="kind" aria-label="按类型筛选"><option value="">全部类型</option>{options}</select>
  </div>
</header>
<main>{''.join(cards) or '<p class="empty">还没有笔记。</p>'}<p class="empty" id="empty" style="display:none">没有匹配的笔记。</p></main>
<footer>由 agent-notes 导出 · 单文件，断网可读</footer>
<script>{EXPORT_JS}</script></body></html>"""


def bundle(notes: list[dict], generated_at: str | None = None) -> dict:
    stamp = generated_at or datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    return {"schema": BUNDLE_SCHEMA, "exported_at": stamp, "count": len(notes), "notes": notes}


def export(service, out: str | Path, note_ids: list[str] | None = None, fmt: str = "html",
           filters: dict | None = None, title: str = "我的笔记") -> dict:
    """按 id 列表或筛选条件导出；两者都没给就导出全部。"""
    if note_ids:
        notes = [service.get(item) for item in note_ids]
    else:
        rows = service.list(**{**(filters or {}), "limit": 0})
        notes = [service.get(row["id"]) for row in rows]
    target = Path(out).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        text = json.dumps(bundle(notes), ensure_ascii=False, indent=2)
        mime = "application/json"
    elif fmt == "html":
        text = render_html(notes, title=title)
        mime = "text/html"
    else:
        raise ValueError(f"不支持的导出格式：{fmt}（可选 html / json）")
    tmp = target.with_name(target.name + ".tmp")
    # newline="" 关掉换行转换：Windows 上默认会把 \n 变成 \r\n，
    # 于是返回的 bytes 和磁盘实际大小差出「行数个字节」，核对文件时对不上。
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    tmp.replace(target)
    return {"ok": True, "count": len(notes), "path": str(target), "format": fmt,
            "mime": mime, "bytes": len(text.encode("utf-8"))}
