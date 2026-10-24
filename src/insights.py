"""数据中心：把原「评测看板」与「汇报页」合并为一页，配可收起的侧栏。

为什么用侧栏而不是顶部标签：模块有六块，横向标签在窄屏会挤成滚动条；
侧栏收起后宽度归零、主内容拿到全部横向空间，展开/收起只动一个变量。
报告的长文不再重复铺在页面里，只留四个关键数字与下载入口。
"""
from __future__ import annotations

from html import escape

from .theme import BRAND, icon, shell
from .web_pages import DASHBOARD_MODAL, DASHBOARD_PANELS, DASHBOARD_SCRIPT, DASH_CSS

NAV_ITEMS = (
    ("p-overview", "概览", "chart"),
    ("p-quality", "质量", "shield"),
    ("p-cases", "用例", "layers"),
    ("p-feedback", "反馈", "chat"),
    ("p-trace", "日志", "clock"),
    ("p-report", "汇报", "doc"),
)


INSIGHTS_CSS = """
/* ---------- 数据中心布局 ---------- */
.ins-wrap{max-width:1160px;padding-top:22px;}
.ins-shell{display:flex;align-items:flex-start;}
.ins-side{
  flex:0 0 auto;width:210px;margin-right:20px;position:sticky;top:calc(var(--nav-h) + 16px);
  overflow:hidden;transition:width .26s ease,margin-right .26s ease,opacity .18s ease;
}
.ins-shell.collapsed .ins-side{width:0;margin-right:0;opacity:0;pointer-events:none;}
.ins-side-in{width:210px;}
.ins-side-card{
  background:var(--surface);border:1px solid var(--line);border-radius:14px;
  padding:12px;box-shadow:var(--sh-1);
}
.ins-side-head{display:flex;align-items:center;gap:8px;padding:2px 4px 10px;border-bottom:1px solid var(--line);margin-bottom:8px;}
.ins-side-title{font-size:11.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);}
.ins-side-head .pill{margin-left:auto;}
.ins-nav{display:flex;flex-direction:column;gap:2px;}
.ins-nav a{
  display:flex;align-items:center;gap:9px;padding:8px 9px;border-radius:8px;font-size:13px;
  color:var(--muted);white-space:nowrap;transition:background .15s ease,color .15s ease;
}
.ins-nav a:hover{background:#f3f5fa;color:var(--ink);}
.ins-nav a.active{background:var(--brand-soft);color:var(--brand-600);font-weight:600;}
.ins-nav a .ic{flex:none;opacity:.85;}
.ins-side-foot{margin-top:10px;padding:10px 6px 0;border-top:1px solid var(--line);font-size:11.5px;color:var(--faint);line-height:1.7;}
.ins-main{flex:1;min-width:0;}
.ins-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px;}
.ins-head h1{font-size:24px;letter-spacing:-.03em;}
.ins-sub{font-size:12px;color:var(--faint);margin-top:2px;}
.ins-toggle{
  width:32px;height:32px;flex:none;display:inline-flex;align-items:center;justify-content:center;
  border:1px solid var(--line);border-radius:9px;background:var(--surface);color:var(--muted);cursor:pointer;
  transition:background .16s ease,color .16s ease,border-color .16s ease;
}
.ins-toggle:hover{background:#f3f5fa;color:var(--ink);border-color:var(--line-2);}
.ins-shell.collapsed .ins-toggle{color:var(--brand-600);border-color:#d5ddfe;background:var(--brand-tint);}
.ins-note{font-size:11.5px;color:var(--faint);margin-top:10px;}
.ins-report-kpis{grid-template-columns:repeat(4,1fr);}
[data-theme="dark"] .ins-nav a:hover{background:#1a253c;color:var(--ink);}
[data-theme="dark"] .ins-toggle:hover{background:#1a253c;color:var(--ink);}
[data-theme="dark"] .ins-shell.collapsed .ins-toggle{background:var(--brand-tint);border-color:#2f4a86;color:#a9bcff;}

@media (max-width:900px){
  .ins-wrap{padding-top:16px;}
  .ins-shell{flex-direction:column;}
  .ins-side{position:static;width:100%;margin:0 0 10px;max-height:360px;transition:max-height .26s ease,opacity .18s ease,margin-bottom .26s ease;}
  .ins-shell.collapsed .ins-side{width:100%;max-height:0;margin-bottom:0;opacity:0;}
  .ins-side-in{width:100%;}
  .ins-side-card{padding:10px;}
  .ins-nav{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;}
  .ins-nav a{padding:8px 6px;justify-content:center;font-size:12.5px;}
  .ins-nav a .ic{display:none;}
  .ins-side-foot{display:none;}
  .ins-report-kpis{grid-template-columns:repeat(2,1fr);}
}
@media (max-width:560px){
  .ins-head h1{font-size:21px;}
  .ins-sub{display:none;}
  .ins-panel.card{padding:15px;}
}
"""


SIDEBAR_JS = """
(function(){
  var shell=document.getElementById('insShell'),
      side=document.getElementById('insSide'),
      btn=document.getElementById('sideToggle'),
      KEY='ins_side_collapsed';
  if(!shell||!side||!btn) return;
  function setCollapsed(collapsed, save){
    shell.classList.toggle('collapsed', collapsed);
    btn.setAttribute('aria-expanded', String(!collapsed));
    btn.setAttribute('aria-label', collapsed?'展开侧栏':'收起侧栏');
    btn.title=collapsed?'展开侧栏':'收起侧栏';
    if(collapsed){ side.setAttribute('inert',''); }
    else{ side.removeAttribute('inert'); }
    if(save){ try{ localStorage.setItem(KEY, collapsed?'1':'0'); }catch(e){} }
  }
  btn.addEventListener('click', function(){
    setCollapsed(!shell.classList.contains('collapsed'), true);
  });
  var saved=null;
  try{ saved=localStorage.getItem(KEY); }catch(e){}
  var narrow=window.matchMedia('(max-width:900px)').matches;
  setCollapsed(saved===null?narrow:saved==='1', false);

  // 窄屏选完模块自动收起，避免侧栏占掉半屏
  side.addEventListener('click', function(e){
    if(e.target.closest('a') && window.matchMedia('(max-width:900px)').matches){
      setCollapsed(true, true);
    }
  });

  // 看板脚本只定义了函数，按钮没有绑事件；这里一次补齐
  var refresh=document.getElementById('refresh');
  if(refresh) refresh.addEventListener('click', function(){ loadAll(); });
  var runDocs=document.getElementById('runDocs');
  if(runDocs) runDocs.addEventListener('click', function(){ runCases('docs'); });
  var runAll=document.getElementById('runAll');
  if(runAll) runAll.addEventListener('click', function(){ runCases('all'); });
})();
"""


def _kpi(value, label: str, sub: str = "", accent: bool = False) -> str:
    cls = "kpi accent" if accent else "kpi"
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    return f'<div class="{cls}"><div class="k">{label}</div><div class="v">{value}</div>{sub_html}</div>'


def _pct(value) -> str:
    try:
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return "—"


def _report_panel(data: dict, kb: dict | None) -> str:
    knowledge = data.get("knowledge") or {}
    cases = data.get("cases") or {}
    l1 = data.get("l1") or []
    l3 = (data.get("l3") or {}).get("avg") or {}
    metrics = data.get("metrics") or {}
    p95 = (metrics.get("latency_ms") or {}).get("p95")
    best = max(l1, key=lambda row: row.get("pass_rate") or 0) if l1 else None
    files = knowledge.get("files") or []
    chunks = knowledge.get("chunks") or 0

    rows = "".join(
        f'<tr><td>{escape(str(row.get("label") or row.get("file") or "—"))}</td>'
        f'<td class="num">{row.get("total") or 0}</td>'
        f'<td class="num {"ok" if (row.get("pass_rate") or 0) >= 0.9 else "warn"}">'
        f'{_pct(row.get("pass_rate"))}</td></tr>'
        for row in l1
    )
    table = (
        '<div class="table-wrap"><table><thead><tr><th>评测轮次</th><th class="num">用例</th>'
        f'<th class="num">通过率</th></tr></thead><tbody>{rows}</tbody></table></div>'
        if rows else
        '<div class="empty">还没有评测报告，先跑一次 L1 基线。</div>'
    )
    version = (kb or {}).get("active") or "—"
    generated = data.get("generated_at") or "—"
    return f"""
<section class="panel ins-panel card" id="p-report">
  <div class="card-head">
    {icon("doc", 15)}
    <h3>汇报</h3><span class="hint">可下载独立 HTML</span>
    <span class="spacer"></span>
    <a class="btn sm" href="/api/report/export">{icon("download", 13)} 下载 HTML</a>
  </div>
  <div class="kpis ins-report-kpis">
    {_kpi(f"{chunks}<small> 块</small>", "知识库规模", f"{len(files)} 份文档")}
    {_kpi(cases.get("total", 0), "评测用例", "基础 + 反馈 + 文档")}
    {_kpi(_pct(best.get("pass_rate")) if best else "—", "L1 通过率", "确定性断言", True)}
    {_kpi(l3.get("faithfulness") or "—", "L3 忠实度", "裁判评分")}
  </div>
  <div style="margin-top:14px">{table}</div>
  <div class="ins-note">知识库 {version} · 数据生成于 {generated} · 完整图表与口径见下载文件</div>
</section>
"""


def render(data: dict, kb: dict | None = None) -> str:
    knowledge = data.get("knowledge") or {}
    chunks = knowledge.get("chunks") or 0
    files = len(knowledge.get("files") or [])
    version = (kb or {}).get("active") or "单目录"

    link_parts = []
    for index, (anchor, label, ic_name) in enumerate(NAV_ITEMS):
        active = ' class="active"' if index == 0 else ""
        link_parts.append(
            f'<a href="#{anchor}"{active}>{icon(ic_name, 15)}<span>{label}</span></a>')
    links = "".join(link_parts)
    sidebar = f"""
<aside class="ins-side" id="insSide" aria-label="模块导航">
  <div class="ins-side-in">
    <div class="ins-side-card">
      <div class="ins-side-head">
        <span class="ins-side-title">模块</span>
        <span class="pill">{version}</span>
      </div>
      <nav class="ins-nav" id="tabs">{links}</nav>
      <div class="ins-side-foot">{files} 份文档 · {chunks} 个知识块</div>
    </div>
  </div>
</aside>"""

    head = f"""
<div class="ins-head">
  <button class="ins-toggle" id="sideToggle" type="button" aria-controls="insSide"
          aria-expanded="true" aria-label="收起侧栏" title="收起侧栏">{icon("side", 16)}</button>
  <div>
    <h1>数据中心</h1>
    <div class="ins-sub">评测 · 运行 · 汇报</div>
  </div>
  <span class="spacer"></span>
  <span class="pill" id="stamp">加载中…</span>
  <button class="btn sm" id="refresh" type="button">{icon("refresh", 13)} 刷新</button>
</div>"""

    body = (
        '<main class="wrap ins-wrap"><div class="ins-shell" id="insShell">'
        f"{sidebar}<div class=\"ins-main\">{head}{DASHBOARD_PANELS}{_report_panel(data, kb)}</div>"
        f"</div>{DASHBOARD_MODAL}</main>"
    )
    return shell("insights", "数据中心 · " + BRAND, body, DASHBOARD_SCRIPT + SIDEBAR_JS, DASH_CSS + INSIGHTS_CSS)
