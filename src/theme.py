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
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/>',
    "moon": '<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/>',
    "side": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
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
.theme-toggle{
  flex:none;width:32px;height:32px;margin-left:2px;border-radius:9px;cursor:pointer;
  display:inline-flex;align-items:center;justify-content:center;
  border:1px solid var(--line);background:var(--surface);color:var(--muted);
  transition:background .16s ease,color .16s ease,border-color .16s ease;
}
.theme-toggle:hover{background:#f3f5fa;color:var(--ink);border-color:var(--line-2);}
.theme-toggle .ic-sun{display:none;}
[data-theme="dark"] .theme-toggle .ic-sun{display:inline-flex;}
[data-theme="dark"] .theme-toggle .ic-moon{display:none;}
@media (max-width:640px){.theme-toggle{width:30px;height:30px;}}

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
/* ============ 深色模式 ============
   只换令牌 + 少量写死浅色的组件；页面私有样式在 theme 之后输出，
   所以这段必须最后加载（shell/报告页都把 DARK_CSS 放在页面 CSS 之后）。 */
[data-theme="dark"]{
  color-scheme:dark;
  --ink:#eef2ff; --text:#d5dcec; --muted:#a9b4c9; --faint:#8f9bb3;
  --line:#243049; --line-2:#2f3d59;
  --bg:#0b1120; --surface:#111827; --surface-2:#0f172a;
  --brand:#7f9cff; --brand-600:#93aaff; --brand-2:#a78bfa; --brand-soft:#1b2a4d; --brand-tint:#141f38;
  --ok:#34d399; --ok-soft:#0f2f26; --warn:#fbbf24; --warn-soft:#33260c; --bad:#f87171; --bad-soft:#3a1518;
  --sh-1:0 1px 2px rgba(0,0,0,.45); --sh-2:0 12px 32px -18px rgba(0,0,0,.85);
  --sh-3:0 30px 70px -30px rgba(0,0,0,.9);
}
[data-theme="dark"] body{
  background-image:radial-gradient(900px 420px at 50% -180px,#17244d 0%,rgba(11,17,32,0) 70%);
}
[data-theme="dark"] ::selection{background:#2b3f75;color:#eef2ff;}
[data-theme="dark"] code{background:#182338;border-color:var(--line);color:#c7d2e8;}
[data-theme="dark"] .nav{background:rgba(15,23,42,.86);border-bottom-color:rgba(36,48,73,.9);}
[data-theme="dark"] .nav nav a:hover{background:#182338;color:var(--ink);}
[data-theme="dark"] .nav .nav-tag{background:#16213a;border-color:var(--line);color:#b9c6e2;}
[data-theme="dark"] .site-foot{background:var(--surface);}
[data-theme="dark"] .theme-toggle{border-color:var(--line-2);background:#16213a;color:#c7d2e8;}
[data-theme="dark"] .theme-toggle:hover{background:#1d2a44;color:var(--ink);}
[data-theme="dark"] .btn.ghost{background:var(--surface);border-color:var(--line-2);color:var(--text);}
[data-theme="dark"] .btn.ghost:hover{background:#182338;border-color:#3a4a6b;color:var(--ink);}
[data-theme="dark"] .btn.quiet:hover{background:#1a253c;color:var(--ink);}
[data-theme="dark"] .btn.danger-ghost{background:var(--surface);border-color:#5a2a2d;color:#fca5a5;}
[data-theme="dark"] .btn.danger-ghost:hover{background:var(--bad-soft);}
[data-theme="dark"] .kpi{background:var(--surface);}
[data-theme="dark"] .kpi:hover{border-color:#33425f;}
[data-theme="dark"] .kpi.accent{background:linear-gradient(160deg,#15213c,#111827 62%);border-color:#2b3a5c;}
[data-theme="dark"] .table-wrap{background:var(--surface);}
[data-theme="dark"] thead th{background:#16213a;color:#93a1bb;border-bottom-color:var(--line);}
[data-theme="dark"] tbody td{border-bottom-color:#1d2942;}
[data-theme="dark"] tbody tr:hover td{background:#16213a;}
[data-theme="dark"] .bar{background:#1c2942;}
[data-theme="dark"] .empty .ic{color:#4a5a78;}
[data-theme="dark"] .pill{background:#182338;border-color:var(--line);color:#b6c2da;}
[data-theme="dark"] .pill.ok{background:var(--ok-soft);border-color:#1f5a45;color:#6ee7b7;}
[data-theme="dark"] .pill.warn{background:var(--warn-soft);border-color:#5a4413;color:#fcd34d;}
[data-theme="dark"] .pill.bad{background:var(--bad-soft);border-color:#5a2a2d;color:#fca5a5;}
[data-theme="dark"] .pill.brand{background:var(--brand-soft);border-color:#2f4a86;color:#a9bcff;}
[data-theme="dark"] .tag{background:var(--brand-soft);color:#a9bcff;}
[data-theme="dark"] .note{background:var(--warn-soft);border-color:#4a3a14;color:#f4d58a;}
[data-theme="dark"] .note.info{background:var(--brand-tint);border-color:#26375c;color:#b9c8ef;}
[data-theme="dark"] .modal-card{background:var(--surface);}
[data-theme="dark"] .field label{color:#a9b4c9;}
[data-theme="dark"] .field input,[data-theme="dark"] .field select,[data-theme="dark"] .field textarea{
  background:#0f172a;border-color:var(--line-2);color:var(--text);
}
[data-theme="dark"] #toasts .toast{background:#1b2743;border:1px solid #2f3d59;color:#eef2ff;}

/* ---------- 页面私有组件 ---------- */
[data-theme="dark"] .stat-strip{background:var(--surface);}
[data-theme="dark"] .chat-shell,[data-theme="dark"] .ans-card,[data-theme="dark"] .ex-card,
[data-theme="dark"] .composer,[data-theme="dark"] .src-drawer{background:var(--surface);}
[data-theme="dark"] .empty-chat .art{background:linear-gradient(160deg,#182544,#0f172a);}
[data-theme="dark"] .src-close,[data-theme="dark"] .kb-modal-head button{background:#1c2942;color:var(--text);}
[data-theme="dark"] .src-text mark{background:#4a3a12;color:#fde68a;}
[data-theme="dark"] .sim-q{background:#241c0c;border-color:#4a3a14;color:#f4d58a;}
[data-theme="dark"] .sim-q:hover{border-color:#7a6224;background:#2b2210;}
[data-theme="dark"] .sk{background:linear-gradient(90deg,#182338 0%,#21304d 40%,#182338 80%);}
[data-theme="dark"] .composer-box{background:#0f172a;border-color:var(--line-2);}
[data-theme="dark"] .composer-hint kbd{background:#1c2942;border-color:var(--line);color:#a9b4c9;}
[data-theme="dark"] .drop{background:linear-gradient(180deg,#141f38,#0f172a);border-color:#33425f;}
[data-theme="dark"] .chips input,[data-theme="dark"] .kb-search,[data-theme="dark"] .appr-token input{background:#0f172a;color:var(--text);}
[data-theme="dark"] .chips button:hover{background:#1c2942;color:var(--ink);}
[data-theme="dark"] .ftype.pdf{background:#3a1518;color:#fca5a5;}
[data-theme="dark"] .ftype.docx{background:#1b2a4d;color:#a9bcff;}
[data-theme="dark"] .ftype.md{background:#0f2f26;color:#6ee7b7;}
[data-theme="dark"] .ftype.txt{background:#1c2942;color:#b6c2da;}
[data-theme="dark"] .kw-row td{background:#141f38;}
[data-theme="dark"] .kw-chip{background:#0f172a;border-color:var(--line-2);color:#c7d2e8;}
[data-theme="dark"] .approve{background:#1f1a0d;border-color:#4a3a14;}
[data-theme="dark"] .kb-modal{background:var(--surface);}
[data-theme="dark"] .tabs a.active{background:var(--surface);border-color:var(--line);}
[data-theme="dark"] .donut::after{background:var(--surface);box-shadow:0 0 0 1px #1c2942 inset;}
[data-theme="dark"] .score-tile{background:linear-gradient(180deg,#141f38,#111827);}
[data-theme="dark"] .dash-select{background:var(--surface);color:var(--text);}

/* ---------- 汇报页 ---------- */
[data-theme="dark"] .rp-nav{background:linear-gradient(180deg,rgba(11,17,32,.97) 62%,rgba(11,17,32,0));}
[data-theme="dark"] .rp-nav a:hover{background:#1c2942;color:var(--ink);}
[data-theme="dark"] .rp-nav a.active{background:var(--surface);border-color:var(--line);}
[data-theme="dark"] .arch{background:linear-gradient(180deg,#141f38,#111827);}
[data-theme="dark"] .rp-score{background:linear-gradient(180deg,#141f38,#111827);}
[data-theme="dark"] .rp-list{color:#c3ccdf;}
[data-theme="dark"] .rp-list li::marker{color:#6b7a96;}
[data-theme="dark"] .axis .ic.is,.score.s5,.score.s4{background:#0f2f26;color:#6ee7b7;}
[data-theme="dark"] .axis .ic.not,.score.s2,.score.s1{background:#3a1518;color:#fca5a5;}
[data-theme="dark"] .score.s3{background:#33260c;color:#fcd34d;}

/* ---------- 减动效 ----------
   系统开启「减少动态效果」后，所有过渡/动画压到 0.01ms：
   不是关掉可见性，只是让位移、脉动、淡入不再发生。 */
@media (prefers-reduced-motion: reduce){
  html{scroll-behavior:auto;}
  *,*::before,*::after{
    animation-duration:.01ms !important;
    animation-iteration-count:1 !important;
    transition-duration:.01ms !important;
    scroll-behavior:auto !important;
  }
}
"""


def nav(active: str = "", links: bool = True) -> str:
    items = [("ask", "/ask", "问答"), ("kb", "/kb", "知识库")]
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
        f"{nav_html}"
        f'<button class="theme-toggle" id="themeToggle" type="button" aria-label="切换深色模式" title="切换深色模式">'
        f'<span class="ic-moon">{icon("moon", 16)}</span>'
        f'<span class="ic-sun">{icon("sun", 16)}</span></button>'
        "</div></header>"
    )


def footer(links: bool = True) -> str:
    nav_links = (
        '<div class="foot-links"><a href="/ask">问答</a><a href="/kb">知识库</a></div>'
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


THEME_HEAD = (
    "<script>(function(){try{var s=localStorage.getItem('rag_theme');"
    "var t=(s==='dark'||s==='light')?s:(window.matchMedia&&"
    "window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');"
    "document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>"
)

THEME_JS = """
(function(){
  var root=document.documentElement;
  var btn=document.getElementById('themeToggle');
  function current(){return root.getAttribute('data-theme')==='dark'?'dark':'light';}
  function apply(t){
    root.setAttribute('data-theme',t);
    try{ localStorage.setItem('rag_theme',t); }catch(e){}
    if(btn) btn.setAttribute('aria-label',t==='dark'?'切换到浅色模式':'切换到深色模式');
  }
  if(btn) btn.addEventListener('click',function(){ apply(current()==='dark'?'light':'dark'); });
})();
"""


def shell(active: str, title: str, body: str, script: str = "", css: str = "") -> str:
    """完整页面骨架。css 为页面私有样式，追加在设计系统之后。"""
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{THEME_HEAD}"
        f'<meta name="color-scheme" content="light dark">'
        '<link rel="icon" href="data:,">'
        f"<title>{title}</title><style>{BASE_CSS}{css}</style></head><body>"
        f"{nav(active)}{body}{footer()}"
        f"<div id=\"toasts\"></div><script>{script}</script><script>{THEME_JS}</script></body></html>"
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
