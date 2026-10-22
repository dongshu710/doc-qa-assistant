"""统一设计系统：设计令牌 + 基础组件样式 + 页头/页脚/骨架。

五个页面（首页 / 问答 / 知识库 / 看板 / 汇报）共用这一份，避免各写一套导致观感割裂。
仍然是纯静态字符串、零外部依赖：不引 CDN、不引字体文件，离线可用。
"""
import os

from .profiles import get_profile
from .version import __version__

PROFILE = get_profile(os.getenv("APP_PROFILE"))
BRAND = PROFILE.app_name
TOPIC = PROFILE.topic_label

# ---------------------------------------------------------------- 图标（inline SVG）
# 统一 24 栅格、1.7 描边、currentColor，避免外部图标库。
ICON = {
    "doc": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/>',
    "shield": '<path d="M12 3l7 3v6c0 4.4-2.9 7.4-7 9-4.1-1.6-7-4.6-7-9V6z"/><path d="m9 12 2 2 4-4"/>',
    "chart": '<path d="M3 3v18h18"/><path d="m7 15 4-5 3 3 5-7"/>',
    "bolt": '<path d="M13 2 4 14h6l-1 8 9-12h-6z"/>',
    "upload": '<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
    "check": '<path d="m20 6-11 11-5-5"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/>',
    "arrow": '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    "spark": '<path d="m12 3 2.2 5.6L20 10.8l-4.4 3.9L16.9 21 12 17.8 7.1 21l1.3-6.3L4 10.8l5.8-2.2z"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V5h6v2"/><path d="M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/>',
    "wand": '<path d="m15 4 5 5L9 20H4v-5z"/><path d="m13 6 5 5"/>',
    "external": '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "alert": '<path d="M12 3 2 21h20z"/><path d="M12 9v5M12 17h.01"/>',
    "chat": '<path d="M4 5h16v11H9l-5 4z"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "download": '<path d="M12 4v12"/><path d="m7 11 5 5 5-5"/><path d="M4 18v2h16v-2"/>',
    "book": '<path d="M4 5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1-2-2z"/><path d="M8 3v18"/>',
    "chevron": '<path d="m9 6 6 6-6 6"/>',
    "target": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
}


def icon(name: str, size: int = 16, cls: str = "ic") -> str:
    body = ICON.get(name, "")
    return (
        f'<svg class="{cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{body}</svg>'
    )


MARK = (
    '<span class="mark"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M6 3.5h7.5L18 8v12.5H6z"/><path d="M13.5 3.5V8H18"/><path d="M9 12.5h6M9 16h4"/></svg></span>'
)

BASE_CSS = """
/* ============ 设计令牌 ============ */
:root{
  --ink:#0a1020; --text:#1b2436; --muted:#4a5468; --faint:#667085;
  --line:#e8ebf2; --line-2:#dce1ec;
  --bg:#f6f7fb; --surface:#fff; --surface-2:#fbfcfe;
  --brand:#2f5cf6; --brand-600:#2449d8; --brand-2:#7a5cfb; --brand-soft:#eef2ff; --brand-tint:#f6f8ff;
  --ok:#0f9d63; --ok-soft:#e9f9f1; --warn:#b26a00; --warn-soft:#fff7e8; --bad:#d92d20; --bad-soft:#fef1f0;
  --r-sm:10px; --r:14px; --r-lg:18px; --r-xl:24px;
  --sh-1:0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.03);
  --sh-2:0 10px 30px -18px rgba(16,24,40,.22), 0 2px 8px rgba(16,24,40,.04);
  --sh-3:0 30px 70px -30px rgba(10,16,32,.35);
  --font:"Inter","PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"JetBrains Mono","SFMono-Regular",Consolas,"Liberation Mono",monospace;
  --nav-h:64px;
}
*,*::before,*::after{box-sizing:border-box;}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth;}
body{
  margin:0;font-family:var(--font);color:var(--text);background:var(--bg);
  font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased;overflow-x:hidden;
  min-height:100vh;display:flex;flex-direction:column;
  background-image:radial-gradient(900px 420px at 50% -180px,#e9edff 0%,rgba(246,247,251,0) 70%);
  background-repeat:no-repeat;
}
a{color:inherit;text-decoration:none;}
button{font-family:inherit;}
h1,h2,h3,h4{margin:0;color:var(--ink);font-weight:700;letter-spacing:-.02em;line-height:1.3;}
p{margin:0;line-height:1.75;}
code{font-family:var(--mono);font-size:.9em;background:#f2f4f9;border:1px solid var(--line);border-radius:5px;padding:1px 5px;color:#334155;}
::selection{background:#dbe3ff;color:#101a3a;}
:focus-visible{outline:2px solid var(--brand);outline-offset:2px;border-radius:8px;}

/* ============ 布局 ============ */
.wrap{width:100%;max-width:1120px;margin:0 auto;padding:28px 22px 72px;}
main{flex:1 0 auto;}
.wrap.narrow{max-width:980px;}
.muted{color:var(--muted);}
.faint{color:var(--faint);}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums;}
.eyebrow{font-size:12px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--brand);display:flex;align-items:center;gap:8px;}
.eyebrow::before{content:"";width:16px;height:1.5px;background:var(--brand);border-radius:2px;}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;}
@media (max-width:860px){ .grid2,.grid3,.grid4{grid-template-columns:1fr;} }
.stack{display:flex;flex-direction:column;gap:16px;}
.row{display:flex;align-items:center;gap:10px;}
.spacer{flex:1;}

/* ============ 页头 ============ */
.nav{
  position:sticky;top:0;z-index:50;height:var(--nav-h);
  background:rgba(255,255,255,.82);backdrop-filter:saturate(180%) blur(14px);
  -webkit-backdrop-filter:saturate(180%) blur(14px);border-bottom:1px solid rgba(232,235,242,.9);
}
.nav-inner{max-width:1120px;height:100%;margin:0 auto;padding:0 22px;display:flex;align-items:center;gap:18px;}
.brand{display:flex;align-items:center;gap:11px;min-width:0;}
.mark{
  width:32px;height:32px;border-radius:10px;flex:none;color:#fff;
  background:linear-gradient(140deg,var(--brand) 0%,var(--brand-2) 100%);
  box-shadow:0 6px 14px -6px rgba(47,92,246,.7), inset 0 1px 0 rgba(255,255,255,.35);
  display:flex;align-items:center;justify-content:center;
}
.mark svg{width:18px;height:18px;}
.brand-text{display:flex;flex-direction:column;line-height:1.15;min-width:0;}
.brand-text b{font-size:14.5px;font-weight:700;color:var(--ink);letter-spacing:-.01em;white-space:nowrap;}
.brand-text i{font-style:normal;font-size:12px;color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.nav nav{display:flex;gap:2px;margin-left:auto;}
.nav nav a{
  position:relative;padding:8px 13px;border-radius:9px;font-size:13.5px;color:var(--muted);
  transition:color .16s ease,background .16s ease;
}
.nav nav a:hover{background:#f3f5fa;color:var(--ink);}
.nav nav a.active{color:var(--brand);font-weight:600;background:var(--brand-soft);}
.nav .nav-tag{
  font-size:12px;font-weight:600;color:#4b5b7c;background:#f2f5fb;border:1px solid var(--line);
  padding:3px 9px;border-radius:999px;white-space:nowrap;
}
@media (max-width:640px){
  /* iOS Safari 在输入框字号 <16px 时会强制放大页面，表现为「点一下界面就变大」 */
  input,textarea,select{font-size:16px;}
  .nav-inner{padding:0 14px;gap:8px;}
  .brand-text i{display:none;}
  .nav-tag{display:none;}
  .nav nav{gap:0;min-width:0;overflow-x:auto;scrollbar-width:none;}
  .nav nav::-webkit-scrollbar{display:none;}
  .nav nav a{padding:7px 8px;font-size:12.5px;white-space:nowrap;}
}
@media (max-width:430px){
  .nav-inner{padding:0 10px;gap:6px;}
  .brand{gap:8px;}
  .brand-text b{font-size:13px;}
  .nav nav a{padding:6px 7px;font-size:12px;}
}

/* ============ 页脚 ============ */
.site-foot{border-top:1px solid var(--line);background:#fff;margin-top:20px;}
.foot-inner{max-width:1120px;margin:0 auto;padding:28px 22px;display:flex;gap:28px;align-items:flex-start;flex-wrap:wrap;}
.foot-brand{display:flex;align-items:center;gap:10px;color:var(--ink);font-weight:600;font-size:13.5px;}
.foot-brand .mark{width:26px;height:26px;border-radius:8px;}
.foot-brand .mark svg{width:15px;height:15px;}
.foot-links{display:flex;gap:18px;font-size:12.5px;color:var(--muted);flex-wrap:wrap;}
.foot-links a:hover{color:var(--brand);}
.foot-note{margin-left:auto;max-width:420px;font-size:12px;color:var(--faint);line-height:1.7;text-align:right;}
@media (max-width:760px){.foot-note{margin-left:0;text-align:left;}}

/* ============ 按钮 ============ */
.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:7px;
  padding:10px 16px;border:1px solid transparent;border-radius:10px;
  background:linear-gradient(180deg,#3a66ff,#2f5cf6);color:#fff;
  font-size:13.5px;font-weight:600;cursor:pointer;white-space:nowrap;
  box-shadow:0 6px 16px -10px rgba(47,92,246,.9), inset 0 1px 0 rgba(255,255,255,.22);
  transition:transform .12s ease, box-shadow .16s ease, background .16s ease;
}
.btn:hover{background:linear-gradient(180deg,#3560f5,#2749d8);box-shadow:0 10px 22px -12px rgba(47,92,246,.95);}
.btn:active{transform:translateY(1px);}
.btn[disabled]{opacity:.55;cursor:not-allowed;transform:none;box-shadow:none;}
.btn.ghost{background:#fff;color:var(--text);border-color:var(--line-2);box-shadow:var(--sh-1);}
.btn.ghost:hover{background:#fbfcff;border-color:#c4cee6;color:var(--ink);}
.btn.quiet{background:transparent;color:var(--muted);border-color:transparent;box-shadow:none;padding:8px 10px;}
.btn.quiet:hover{background:#f2f5fa;color:var(--ink);}
.btn.danger-ghost{background:#fff;color:var(--bad);border-color:#f3d3d1;box-shadow:none;}
.btn.danger-ghost:hover{background:var(--bad-soft);}
.btn.sm{padding:7px 11px;font-size:12.5px;border-radius:8px;}
.btn.lg{padding:13px 22px;font-size:15px;border-radius:11px;}
.btn .ic{flex:none;}

/* ============ 卡片 ============ */
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:20px;box-shadow:var(--sh-1);}
.card.tight{padding:0;overflow:hidden;}
.card-head{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap;}
.card-head h3{font-size:14.5px;font-weight:650;}
.card-head .hint{font-size:12px;color:var(--faint);font-weight:400;}
.card-head .ic{color:var(--brand);}
.section-head{display:flex;align-items:flex-end;gap:12px;margin:34px 0 14px;}
.section-head h2{font-size:20px;}
.section-head p{font-size:13px;color:var(--muted);margin-left:auto;text-align:right;}
@media (max-width:760px){.section-head{flex-direction:column;align-items:flex-start;gap:4px;} .section-head p{margin-left:0;text-align:left;}}

/* ============ 徽标 / 胶囊 ============ */
.pill{
  display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:500;
  padding:3px 9px;border-radius:999px;background:#f4f6fa;border:1px solid var(--line);color:#54617a;
  white-space:nowrap;
}
.pill.ok{background:var(--ok-soft);border-color:#c8f0dc;color:#0a7a4d;}
.pill.warn{background:var(--warn-soft);border-color:#f6e2bd;color:#8f5400;}
.pill.bad{background:var(--bad-soft);border-color:#f6d3d0;color:#a91e13;}
.pill.brand{background:var(--brand-soft);border-color:#d5ddfe;color:#2a49c8;}
.pill .dot{width:6px;height:6px;border-radius:50%;background:currentColor;}
.tag{display:inline-flex;align-items:center;font-size:12px;font-weight:600;color:var(--brand);background:var(--brand-soft);padding:2px 8px;border-radius:999px;}

/* ============ 指标卡 ============ */
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}
.kpi{
  position:relative;background:#fff;border:1px solid var(--line);border-radius:var(--r);padding:15px 16px;
  box-shadow:var(--sh-1);transition:box-shadow .18s ease, transform .18s ease, border-color .18s ease;
}
.kpi:hover{box-shadow:var(--sh-2);transform:translateY(-1px);border-color:#dfe5f3;}
.kpi .k{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:6px;}
.kpi .k .ic{color:var(--faint);}
.kpi .v{font-size:25px;font-weight:700;color:var(--ink);letter-spacing:-.03em;margin-top:6px;font-variant-numeric:tabular-nums;line-height:1.15;}
.kpi .v small{font-size:13px;font-weight:600;color:var(--muted);margin-left:1px;letter-spacing:0;}
.kpi .sub{font-size:12px;color:var(--faint);margin-top:3px;}
.kpi.accent{background:linear-gradient(160deg,#f7f9ff,#fff 60%);border-color:#dee4fb;}
.kpi.accent .v{color:var(--brand-600);}
@media (max-width:900px){.kpis{grid-template-columns:repeat(2,1fr);}}

/* ============ 表格 ============ */
.table-wrap{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#fff;}
table{width:100%;border-collapse:collapse;font-size:13px;}
thead th{
  text-align:left;padding:10px 14px;background:#fafbfe;border-bottom:1px solid var(--line);
  font-size:12px;font-weight:600;letter-spacing:.04em;color:#7b879c;text-transform:uppercase;white-space:nowrap;
}
tbody td{text-align:left;padding:11px 14px;border-bottom:1px solid #f1f3f8;color:var(--text);vertical-align:middle;}
tbody tr:last-child td{border-bottom:none;}
tbody tr:hover td{background:#fafbff;}
.num{font-variant-numeric:tabular-nums;text-align:right;}
.ok{color:var(--ok);font-weight:600;}
.warn{color:var(--warn);font-weight:600;}
.bad{color:var(--bad);font-weight:600;}

/* ============ 进度条 ============ */
.bar-row{display:flex;align-items:center;gap:11px;margin:9px 0;font-size:13px;}
.bar-row .name{width:104px;flex:none;color:var(--muted);font-size:12.5px;}
.bar{flex:1;height:8px;background:#eef1f7;border-radius:999px;overflow:hidden;}
.bar > i{
  display:block;height:100%;border-radius:999px;
  background:linear-gradient(90deg,#5a7cff,#2f5cf6);
  transition:width .7s cubic-bezier(.22,.8,.3,1);
}
.bar-row .val{width:52px;text-align:right;color:var(--ink);font-size:12.5px;font-variant-numeric:tabular-nums;}

/* ============ 空状态 ============ */
.empty{
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;
  padding:34px 18px;color:var(--faint);text-align:center;font-size:13px;
}
.empty .ic{color:#c3cbdc;}

/* ============ 提示 / 轻提示 ============ */
.note{
  display:flex;gap:9px;align-items:flex-start;padding:11px 13px;border-radius:10px;
  background:var(--warn-soft);border:1px solid #f6e6c8;color:#7a4b00;font-size:12.5px;line-height:1.65;
}
.note .ic{flex:none;margin-top:1px;}
.note.info{background:var(--brand-tint);border-color:#e0e6fb;color:#33437a;}
.note.info .ic{color:var(--brand);}

#toasts{position:fixed;right:18px;bottom:18px;z-index:200;display:flex;flex-direction:column;gap:8px;align-items:flex-end;}
.toast{
  display:flex;align-items:center;gap:8px;max-width:360px;
  padding:11px 14px;border-radius:11px;background:#101a33;color:#f2f5ff;font-size:13px;
  box-shadow:var(--sh-3);animation:toast-in .22s ease both;
}
.toast .ic{color:#8fb0ff;flex:none;}
.toast.err{background:#3d1414;}
.toast.err .ic{color:#ffb4ad;}
@keyframes toast-in{from{opacity:0;transform:translateY(8px) scale(.98);}to{opacity:1;transform:none;}}

/* ============ 弹层 ============ */
.modal{position:fixed;inset:0;z-index:300;display:none;align-items:center;justify-content:center;padding:20px;
  background:rgba(10,16,32,.42);backdrop-filter:blur(3px);}
.modal.open{display:flex;}
.modal-card{width:100%;max-width:440px;background:#fff;border-radius:var(--r-lg);padding:22px;box-shadow:var(--sh-3);
  animation:modal-in .18s ease both;}
@keyframes modal-in{from{opacity:0;transform:translateY(10px) scale(.985);}to{opacity:1;transform:none;}}
.modal-card h3{font-size:16px;margin-bottom:6px;}
.modal-card .modal-sub{font-size:12.5px;color:var(--muted);margin-bottom:16px;line-height:1.7;}
.modal-foot{display:flex;justify-content:flex-end;gap:8px;margin-top:20px;}
.field{display:block;margin-bottom:13px;}
.field label{display:block;font-size:12px;font-weight:600;color:#475467;margin-bottom:6px;}
.field input,.field select,.field textarea{
  width:100%;padding:10px 12px;border:1px solid var(--line-2);border-radius:9px;font-size:13.5px;
  font-family:inherit;color:var(--text);background:#fff;outline:none;transition:border .15s, box-shadow .15s;
}
.field input:focus,.field select:focus,.field textarea:focus{border-color:var(--brand);box-shadow:0 0 0 3px rgba(47,92,246,.12);}
.field .hint{font-size:12px;color:var(--faint);margin-top:5px;}

/* ============ 代码块 ============ */
pre.cmd{
  margin:0;background:#0b1226;color:#dbe4ff;border-radius:12px;padding:16px 18px;overflow:auto;
  font-family:var(--mono);font-size:12.5px;line-height:1.9;border:1px solid #1b2647;
}
pre.cmd .c{color:#7d8db3;}

@media print{
  body{background:#fff;}
  .nav,.site-foot,#toasts,.no-print{display:none !important;}
  .card,.kpi{box-shadow:none;break-inside:avoid;}
}
"""


def nav(active: str = "", links: bool = True) -> str:
    items = [("home", "/", "首页"), ("ask", "/ask", "问答"), ("kb", "/kb", "知识库"),
             ("dash", "/dashboard", "看板"), ("report", "/report", "汇报")]
    nav_html = ""
    if links:
        nav_html = "<nav>%s</nav>" % "".join(
            '<a class="%s" href="%s">%s</a>' % ("active" if key == active else "", url, title)
            for key, url, title in items
        )
    else:
        nav_html = '<nav><span class="pill"><span class="dot" style="background:#0f9d63"></span>离线快照</span></nav>'
    return (
        '<header class="nav"><div class="nav-inner">'
        f'<a class="brand" href="/">{MARK}'
        f'<span class="brand-text"><b>{BRAND}</b><i>{TOPIC}</i></span></a>'
        f'<span class="nav-tag">v{__version__}</span>'
        f"{nav_html}</div></header>"
    )


def footer(links: bool = True) -> str:
    nav_links = (
        '<div class="foot-links"><a href="/">首页</a><a href="/ask">问答</a>'
        '<a href="/kb">知识库</a><a href="/dashboard">看板</a><a href="/report">汇报</a></div>'
        if links else '<div class="foot-links"><span>独立导出 · 离线可看</span></div>'
    )
    return (
        '<footer class="site-foot"><div class="foot-inner">'
        f'<div class="foot-brand">{MARK}<span>{BRAND}</span></div>'
        f'{nav_links}'
        '<div class="foot-note">只依据知识库作答，逐条标注出处；资料不足时明确说明无法找到答案。<br>'
        '演示知识库为模拟样本与公开条款摘录，不构成投资建议。</div>'
        "</div></footer>"
    )


def shell(active: str, title: str, body: str, script: str = "", css: str = "") -> str:
    """完整页面骨架。css 为页面私有样式，追加在设计系统之后。"""
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<meta name="color-scheme" content="light">'
        f"<title>{title}</title><style>{BASE_CSS}{css}</style></head><body>"
        f"{nav(active)}{body}{footer()}"
        f"<div id=\"toasts\"></div><script>{script}</script></body></html>"
    )


# 供页面脚本复用的小工具：转义、toast
JS_UTIL = """
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function toast(msg,isErr){
  var box=document.getElementById('toasts'); if(!box) return;
  var d=document.createElement('div'); d.className='toast'+(isErr?' err':'');
  d.innerHTML='<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="'+((isErr)?'M18 6 6 18M6 6l12 12':'m20 6-11 11-5-5')+'"/></svg><span></span>';
  d.querySelector('span').textContent=msg||'';
  box.appendChild(d);
  setTimeout(function(){ d.style.transition='opacity .25s, transform .25s'; d.style.opacity='0'; d.style.transform='translateY(6px)'; setTimeout(function(){d.remove();},260); }, 2600);
}
"""
