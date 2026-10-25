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
  --ink:#17181c; --text:#2b2d33; --muted:#61646b; --faint:#8a8f98;
  --line:#ececf0; --line-2:#e0e1e6;
  --bg:#ffffff; --surface:#ffffff; --surface-2:#f7f8fa;
  --brand:#4d6bfe; --brand-600:#3d5af0; --brand-2:#4d6bfe; --brand-soft:#eef1ff; --brand-tint:#f6f7ff;
  --ok:#0f9d63; --ok-soft:#e9f9f1; --warn:#b26a00; --warn-soft:#fff7e8; --bad:#d92d20; --bad-soft:#fef1f0;
  --r-sm:8px; --r:12px; --r-lg:16px; --r-xl:20px;
  --sh-1:0 1px 2px rgba(17,18,22,.04);
  --sh-2:0 8px 24px -16px rgba(17,18,22,.18), 0 1px 2px rgba(17,18,22,.04);
  --sh-3:0 24px 56px -28px rgba(17,18,22,.28);
  --font:"Inter","PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"JetBrains Mono","SFMono-Regular",Consolas,"Liberation Mono",monospace;
  --nav-h:56px;
}
*,*::before,*::after{box-sizing:border-box;}
/* 面板自己写了 display:flex，没有这条 hidden 就形同虚设（/files 上曾因此露出设置抽屉） */
[hidden]{display:none !important;}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth;}
body{
  margin:0;font-family:var(--font);color:var(--text);background:var(--bg);
  font-size:14.5px;line-height:1.65;-webkit-font-smoothing:antialiased;overflow-x:hidden;
  min-height:100vh;display:flex;flex-direction:column;
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
  background:rgba(255,255,255,.86);backdrop-filter:saturate(180%) blur(12px);
  -webkit-backdrop-filter:saturate(180%) blur(12px);border-bottom:1px solid var(--line);
}
.nav-inner{max-width:1120px;height:100%;margin:0 auto;padding:0 22px;display:flex;align-items:center;gap:18px;}
.brand{display:flex;align-items:center;gap:11px;min-width:0;}
.mark{
  width:30px;height:30px;border-radius:9px;flex:none;color:#fff;
  background:var(--brand);
  box-shadow:0 4px 12px -6px rgba(77,107,254,.55);
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
.theme-toggle:hover{background:#f3f4f7;color:var(--ink);border-color:var(--line-2);}
/* 已存文件的实体入口：放导航栏右侧，和主题/设置同一排，点开即看文件与正文 */
.nav-files-wrap{position:relative;flex:none;display:inline-flex;margin-left:4px;}
.nav-files{
  flex:none;position:relative;display:inline-flex;align-items:center;gap:7px;height:34px;padding:0 12px;
  border-radius:9px;border:1px solid var(--line);background:var(--surface);color:var(--muted);
  font-size:13px;font-weight:500;cursor:pointer;
  transition:color .15s,border-color .15s,background .15s;
}
.nav-files svg{flex:none;}
.nav-files:hover{color:var(--brand);border-color:var(--brand);background:var(--brand-tint);}
.nav-files[aria-expanded="true"]{color:var(--brand);border-color:var(--brand);background:var(--brand-tint);}
.nav-files .nf-count{
  min-width:18px;height:18px;padding:0 5px;border-radius:999px;background:var(--brand-soft);
  color:var(--brand);font-size:11px;font-weight:700;line-height:18px;text-align:center;
}
.nav-files .nf-count[hidden]{display:none;}
@media (max-width:720px){ .nav-files .nf-label{display:none;} .nav-files{padding:0 9px;} }
.theme-toggle .ic-sun{display:none;}
[data-theme="dark"] .theme-toggle .ic-sun{display:inline-flex;}
[data-theme="dark"] .theme-toggle .ic-moon{display:none;}
@media (max-width:640px){.theme-toggle{width:30px;height:30px;}}

/* ============ 页脚 ============ */
.site-foot{border-top:1px solid var(--line);background:var(--surface);margin-top:20px;}
.foot-inner{max-width:1120px;margin:0 auto;padding:16px 22px;display:flex;gap:20px;align-items:center;
  font-size:12.5px;color:var(--faint);}
.foot-brand{color:var(--muted);font-weight:600;}
.foot-links{display:flex;gap:14px;}
.foot-links a:hover{color:var(--brand);}
.foot-ver{margin-left:auto;font-family:var(--mono);font-size:11.5px;color:var(--faint);
  border:0;background:none;padding:2px 4px;border-radius:5px;cursor:pointer;}
.foot-ver:hover{color:var(--brand);background:var(--surface-2);}

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
  --ink:#f1f2f4; --text:#d6d8dd; --muted:#a3a7af; --faint:#80848c;
  --line:#2b2c31; --line-2:#383940;
  --bg:#17181c; --surface:#1c1d21; --surface-2:#232429;
  --brand:#7c93ff; --brand-600:#93a6ff; --brand-2:#7c93ff; --brand-soft:#262b44; --brand-tint:#1f2130;
  --ok:#34d399; --ok-soft:#0f2f26; --warn:#fbbf24; --warn-soft:#33260c; --bad:#f87171; --bad-soft:#3a1518;
  --sh-1:0 1px 2px rgba(0,0,0,.45); --sh-2:0 12px 32px -18px rgba(0,0,0,.85);
  --sh-3:0 30px 70px -30px rgba(0,0,0,.9);
}
[data-theme="dark"] ::selection{background:#2f3a63;color:#eef2ff;}
[data-theme="dark"] code{background:#232429;border-color:var(--line);color:#c9ccd4;}
[data-theme="dark"] .nav{background:rgba(28,29,33,.88);border-bottom-color:var(--line);}
[data-theme="dark"] .nav nav a:hover{background:var(--surface-2);color:var(--ink);}
[data-theme="dark"] .site-foot{background:var(--surface);}
[data-theme="dark"] .theme-toggle{border-color:var(--line-2);background:var(--surface-2);color:var(--text);}
[data-theme="dark"] .theme-toggle:hover{background:var(--surface);color:var(--ink);}
[data-theme="dark"] .btn.ghost{background:var(--surface);border-color:var(--line-2);color:var(--text);}
[data-theme="dark"] .btn.ghost:hover{background:var(--surface-2);border-color:var(--line-2);color:var(--ink);}
[data-theme="dark"] .btn.quiet:hover{background:var(--surface-2);color:var(--ink);}
[data-theme="dark"] .btn.danger-ghost{background:var(--surface);border-color:#5a2a2d;color:#fca5a5;}
[data-theme="dark"] .btn.danger-ghost:hover{background:var(--bad-soft);}
[data-theme="dark"] .kpi{background:var(--surface);}
[data-theme="dark"] .kpi:hover{border-color:#33425f;}
[data-theme="dark"] .kpi.accent{background:linear-gradient(160deg,#15213c,#111827 62%);border-color:#2b3a5c;}
[data-theme="dark"] .table-wrap{background:var(--surface);}
[data-theme="dark"] thead th{background:var(--surface-2);color:var(--faint);border-bottom-color:var(--line);}
[data-theme="dark"] tbody td{border-bottom-color:var(--line);}
[data-theme="dark"] tbody tr:hover td{background:var(--surface-2);}
[data-theme="dark"] .bar{background:#1c2942;}
[data-theme="dark"] .empty .ic{color:#4a5a78;}
[data-theme="dark"] .pill{background:var(--surface-2);border-color:var(--line);color:var(--muted);}
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
  background:var(--bg);border-color:var(--line-2);color:var(--text);
}
[data-theme="dark"] #toasts .toast{background:var(--surface);border:1px solid var(--line);color:var(--ink);}

/* ---------- 页面私有组件 ---------- */
[data-theme="dark"] .stat-strip{background:var(--surface);}
[data-theme="dark"] .ans-card,[data-theme="dark"] .ex-card,
[data-theme="dark"] .src-drawer{background:var(--surface);}
[data-theme="dark"] .empty-chat .art{background:var(--brand-soft);border-color:var(--line);}
[data-theme="dark"] .src-close,[data-theme="dark"] .kb-modal-head button{background:var(--surface-2);color:var(--text);}
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
        f"{nav_html}"
        # 文件入口：固定在导航栏右侧，位置上不再有第二种解释
        '<div class="nav-files-wrap">'
        '<button class="nav-files" id="filesBtn" type="button" aria-haspopup="dialog" '
        'aria-controls="filesPanel" aria-expanded="false" aria-keyshortcuts="Control+Shift+F" '
        'title="已存文件 · Ctrl+Shift+F">'
        '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M6 3.5h7.5L18 8v12.5H6z"/><path d="M13.5 3.5V8H18"/></svg>'
        '<span class="nf-label">文件</span>'
        '<span class="nf-count" id="filesCount" hidden>0</span></button>'
        # 红点单独成按钮：点它只消提醒，不会顺手把抽屉拉开
        '<button class="files-dot" id="filesDot" type="button" aria-label="消除备份提醒" '
        'title="点一下消除提醒" hidden></button>'
        "</div>"
        f'<button class="theme-toggle" id="themeToggle" type="button" aria-label="切换深色模式" title="切换深色模式">'
        f'<span class="ic-moon">{icon("moon", 16)}</span>'
        f'<span class="ic-sun">{icon("sun", 16)}</span></button>'
        '<button class="nav-gear" id="setBtn" type="button" aria-label="设置" title="设置">'
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round"><path d="M4 6h8M18 6h2M4 12h4M12 12h8M4 18h10"/>'
        '<circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>'
        '</svg></button>'
        "</div></header>"
    )


def footer(links: bool = True) -> str:
    links_html = '<a href="/ask">问答</a><a href="/kb">知识库</a>' if links else "<span>独立导出 · 离线可看</span>"
    return (
        '<footer class="site-foot"><div class="foot-inner">'
        f'<span class="foot-brand">{BRAND}</span>'
        f'<span class="foot-links">{links_html}</span>'
        f'<button class="foot-ver" id="footVer" type="button" title="查看版本与更新">v{__version__}</button>'
        "</div></footer>"
    )


SETTINGS_CSS = """
/* ============ 设置抽屉 ============ */
.nav-gear{width:34px;height:34px;border-radius:10px;border:1px solid var(--line);background:var(--surface);
  color:var(--muted);display:inline-flex;align-items:center;justify-content:center;cursor:pointer;
  transition:color .15s,border-color .15s,background .15s;margin-left:4px;flex:none;position:relative;}
.nav-gear:hover{color:var(--brand);border-color:var(--brand);background:var(--brand-tint);}
.gear-dot{position:absolute;top:5px;right:5px;width:7px;height:7px;border-radius:50%;
  background:var(--bad);box-shadow:0 0 0 1.5px var(--surface);}
.gear-dot[hidden]{display:none;}
.set-mask{position:fixed;inset:0;background:rgba(10,16,32,.32);z-index:70;}
.set-panel{position:fixed;inset:0 0 0 auto;width:min(430px,100vw);background:var(--surface);z-index:71;
  display:flex;flex-direction:column;box-shadow:var(--sh-3);animation:setIn .18s ease;}
@keyframes setIn{from{transform:translateX(16px);opacity:.5}to{transform:none;opacity:1}}
.set-hd{display:flex;align-items:center;gap:10px;padding:16px 18px;border-bottom:1px solid var(--line);}
.set-hd b{font-size:15px;color:var(--ink);}
.set-x{margin-left:auto;width:30px;height:30px;border:0;background:transparent;color:var(--faint);
  font-size:20px;line-height:1;cursor:pointer;border-radius:8px;}
.set-x:hover{background:var(--surface-2);color:var(--ink);}
.set-tabs{display:flex;gap:4px;padding:9px 12px;border-bottom:1px solid var(--line);overflow-x:auto;}
.set-tabs button{border:0;background:transparent;color:var(--muted);font-size:13px;padding:6px 11px;
  border-radius:8px;cursor:pointer;white-space:nowrap;}
.set-tabs button:hover{background:var(--surface-2);color:var(--ink);}
.set-tabs button.on{background:var(--brand-soft);color:var(--brand-600);font-weight:600;}
.set-body{flex:1;overflow-y:auto;padding:16px 18px 28px;}
.set-pane{display:none;flex-direction:column;gap:12px;}
.set-pane.on{display:flex;}
.set-f{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--muted);font-weight:600;}
.set-f input,.set-f select{padding:9px 11px;border:1px solid var(--line-2);border-radius:var(--r-sm);
  background:var(--surface-2);color:var(--text);font-size:13px;font-family:inherit;width:100%;}
.set-f input:focus{border-color:var(--brand);outline:2px solid var(--brand);outline-offset:0;}
.set-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.set-note{font-size:12px;color:var(--faint);line-height:1.6;margin:0;}
.set-note.ok{color:var(--ok);}
.set-note.err{color:var(--bad);}
.set-note a{color:var(--brand);text-decoration:underline;text-underline-offset:2px;}
.set-ver-now{font-size:13px;color:var(--text);}
.set-ver-now b{font-family:var(--mono);font-size:12px;color:var(--ink);}
.set-seg{display:inline-flex;border:1px solid var(--line-2);border-radius:10px;padding:2px;background:var(--surface-2);}
.set-seg button{border:0;background:transparent;padding:6px 14px;border-radius:8px;font-size:13px;
  color:var(--muted);cursor:pointer;}
.set-seg button.on{background:var(--surface);color:var(--ink);font-weight:600;box-shadow:var(--sh-1);}
.set-switch{display:flex;align-items:flex-start;gap:12px;cursor:pointer;padding:12px;
  border:1px solid var(--line);border-radius:var(--r);background:var(--surface-2);}
.set-switch input{position:absolute;opacity:0;width:0;height:0;}
.set-track{flex:none;width:40px;height:22px;border-radius:11px;background:#cfd6e4;position:relative;
  transition:background .18s;margin-top:2px;}
.set-track::after{content:"";position:absolute;top:2px;left:2px;width:18px;height:18px;border-radius:50%;
  background:#fff;transition:transform .18s;box-shadow:0 1px 3px rgba(0,0,0,.2);}
.set-switch input:checked + .set-track{background:var(--brand);}
.set-switch input:checked + .set-track::after{transform:translateX(18px);}
.set-switch input:focus-visible + .set-track{outline:2px solid var(--brand);outline-offset:2px;}
.set-switch-text{display:flex;flex-direction:column;gap:2px;}
.set-switch-text b{font-size:13px;color:var(--ink);}
.set-switch-text i{font-size:12px;color:var(--faint);font-style:normal;line-height:1.5;}
.set-pre{font-family:var(--mono);font-size:11px;line-height:1.55;background:var(--surface-2);
  border:1px solid var(--line);border-radius:var(--r-sm);padding:10px;max-height:210px;overflow:auto;
  white-space:pre-wrap;word-break:break-all;color:var(--text);margin:0;}
.set-path{display:flex;gap:6px;}
.set-path input{flex:1;min-width:0;}
.set-path .btn{flex:none;white-space:nowrap;}
.set-migrate{border:1px solid var(--brand);background:var(--brand-tint);border-radius:var(--r-sm);
  padding:10px 12px;display:flex;flex-direction:column;gap:8px;}
.set-migrate[hidden]{display:none;}
.set-migrate .set-note{color:var(--brand-600);}
.set-notes{display:flex;flex-direction:column;gap:6px;}
.set-note-item{border:1px solid var(--line);border-radius:10px;padding:9px 11px;cursor:pointer;
  background:var(--surface);}
.set-note-item:hover{border-color:var(--brand);background:var(--brand-tint);}
.set-note-item b{display:block;font-size:13px;color:var(--ink);font-weight:600;}
.set-note-item span{font-size:11px;color:var(--faint);}
.set-note-view{font-size:12.5px;line-height:1.7;white-space:pre-wrap;border-top:1px solid var(--line);
  margin-top:8px;padding-top:8px;color:var(--text);}
body.set-open{overflow:hidden;}
@media (max-width:520px){ .set-panel{width:100vw;} }
"""

SETTINGS_HTML = (
    '<div class="set-mask" id="setMask" hidden></div>'
    '<aside class="set-panel" id="setPanel" hidden aria-label="设置">'
    '<div class="set-hd"><b>设置</b>'
    '<button class="set-x" id="setClose" type="button" aria-label="关闭">×</button></div>'
    '<div class="set-tabs" id="setTabs">'
    '<button type="button" data-tab="api" class="on">接口</button>'
    '<button type="button" data-tab="store">存储</button>'
    '<button type="button" data-tab="chat">对话</button>'
    '<button type="button" data-tab="install">安装</button>'
    "</div>"
    '<div class="set-body">'
    '<p class="set-note err" id="setCfgWarn" hidden></p>'

    '<section class="set-pane on" data-pane="api">'
    '<label class="set-f">接口地址<input id="setBase" autocomplete="off" spellcheck="false"></label>'
    '<label class="set-f">模型<input id="setModel" autocomplete="off" spellcheck="false"></label>'
    '<label class="set-f">密钥<input id="setKey" type="password" autocomplete="off" spellcheck="false"></label>'
    '<div class="set-row"><button class="btn sm" id="setSave" type="button">保存</button>'
    '<button class="btn ghost sm" id="setTest" type="button">测试连接</button></div>'
    '<p class="set-note" id="setApiNote"></p>'
    '<p class="set-note">兼容 OpenAI 协议的端点都行，填到 /v1 这一层。</p>'
    "</section>"

    '<section class="set-pane" data-pane="store">'
    '<div class="set-seg" id="setHomeSeg">'
    '<button type="button" data-home="default" class="on">默认位置</button>'
    '<button type="button" data-home="custom">自定义</button></div>'
    '<div class="set-f" id="setHomeWrap" hidden><span>目录</span>'
    '<div class="set-path">'
    '<input id="setHome" placeholder="D:\\我的笔记" autocomplete="off" spellcheck="false">'
    '<button class="btn ghost sm" id="setPick" type="button">选择…</button>'
    "</div></div>"
    '<div class="set-row"><button class="btn sm" id="setHomeSave" type="button">应用</button>'
    '<button class="btn ghost sm" id="setOpen" type="button">打开文件夹</button></div>'
    '<p class="set-note" id="setHomeNote"></p>'
    '<div class="set-migrate" id="setMigrate" hidden>'
    '<p class="set-note" id="setMigrateText"></p>'
    '<div class="set-row"><button class="btn sm" id="setMigrateGo" type="button">复制过来</button>'
    '<button class="btn ghost sm" id="setMigrateNo" type="button">不用</button></div></div>'
    '<p class="set-note">笔记是普通 Markdown，放哪儿都能用别的编辑器打开。</p>'
    "</section>"

    '<section class="set-pane" data-pane="chat">'
    '<label class="set-switch"><input type="checkbox" id="setStoreChat">'
    '<span class="set-track"></span>'
    '<span class="set-switch-text"><b>储存对话内容</b>'
    '<i>关闭时，任何对话都不会写进笔记库</i></span></label>'
    '<p class="set-note" id="setChatNote"></p>'
    "</section>"

    '<section class="set-pane" data-pane="install">'
    '<div class="set-row">'
    f'<span class="set-ver-now">知源 <b>v{__version__}</b></span>'
    '<span class="spacer"></span>'
    '<button class="btn ghost sm" id="setUpdate" type="button">检查更新</button></div>'
    '<p class="set-note" id="setUpdateNote">只查不改：读 GitHub 上的最新版本号，不会自动下载或覆盖本地文件。</p>'
    '<div class="set-row">'
    '<a class="btn sm" id="setDownload" href="#" target="_blank" rel="noopener">下载应用包</a>'
    '<a class="btn ghost sm" id="setDownloadPlugin" href="#" target="_blank" rel="noopener">下载插件包</a>'
    '<a class="btn ghost sm" href="/files" target="_blank" rel="noopener">打开文件页</a></div>'
    '<p class="set-note">应用包＝问答 + 笔记，解压双击即用；插件包＝只有笔记，挂到任意 MCP 客户端。</p>'
    '<div class="set-row">'
    '<button class="btn ghost sm" id="setMcpCopy" type="button">复制配置</button>'
    '<button class="btn ghost sm" id="setMcpInstall" type="button">写入 Claude Desktop</button></div>'
    '<pre class="set-pre" id="setMcpPre">加载中…</pre>'
    '<p class="set-note" id="setMcpNote"></p>'
    '<p class="set-note">WorkBuddy 的「更多选项」里没有放自定义按钮的位置：'
    '要让智能体读写这些笔记，接的是连接器（MCP）；人看的入口在页面右上角「文件」。</p>'
    "</section>"

    "</div></aside>"
)

FILES_CSS = """
/* ============ 文件抽屉（已存内容） ============ */
/* 红点是个独立按钮：点只有 7px，点击区做到 18px，鼠标和手指都点得中 */
.files-dot{position:absolute;top:-5px;right:-5px;width:18px;height:18px;padding:0;border:0;
  background:none;cursor:pointer;}
.files-dot::after{content:"";position:absolute;top:50%;left:50%;width:7px;height:7px;
  margin:-3.5px 0 0 -3.5px;border-radius:50%;background:var(--bad);
  box-shadow:0 0 0 2px var(--surface);transition:transform .12s;}
.files-dot:hover::after{transform:scale(1.4);}
.files-dot:focus-visible{outline:2px solid var(--brand);outline-offset:2px;border-radius:50%;}
.files-dot[hidden]{display:none;}
/* 首次进入指一下入口在哪：位置写死在导航栏，提示只做一次，不打扰 */
.files-tip{position:fixed;z-index:60;max-width:230px;padding:8px 11px;border-radius:9px;
  background:#1f2228;color:#fff;font-size:12px;line-height:1.65;box-shadow:0 10px 24px -12px rgba(0,0,0,.5);}
.files-tip::before{content:"";position:absolute;top:-4px;right:26px;width:8px;height:8px;
  background:#1f2228;transform:rotate(45deg);}
.files-tip kbd{font-family:var(--mono);font-size:11px;background:rgba(255,255,255,.18);
  padding:1px 4px;border-radius:4px;}
/* 独立页面 /files：不套抽屉，直接在正常文档流里两栏 */
.pf-wrap{max-width:1120px;margin:0 auto;padding:22px 22px 40px;width:100%;}
.pf-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:14px;}
.pf-head h1{font-size:20px;letter-spacing:-.02em;margin:0;}
.pf-sub{margin:0;font-size:12.5px;color:var(--muted);}
.pf-actions{margin-left:auto;display:flex;gap:8px;align-items:center;}
.pf-total{font-size:12px;color:var(--faint);}
.pf-grid{display:grid;grid-template-columns:280px minmax(0,1fr);
  border:1px solid var(--line);border-radius:14px;background:var(--surface);overflow:hidden;
  min-height:min(70vh,640px);}
.pf-list{border-right:1px solid var(--line);padding:8px;overflow:auto;max-height:78vh;}
.pf-detail{padding:20px 24px;overflow:auto;max-height:78vh;}
@media (max-width:760px){
  .pf-grid{grid-template-columns:1fr;}
  .pf-list{border-right:0;border-bottom:1px solid var(--line);max-height:38vh;}
  .pf-detail{max-height:none;}
}
.files-mask{position:fixed;inset:0;background:rgba(17,18,22,.26);z-index:70;}
.files-panel{
  position:fixed;top:0;right:0;bottom:0;width:min(760px,96vw);z-index:71;display:flex;flex-direction:column;
  background:var(--surface);border-left:1px solid var(--line);box-shadow:var(--sh-3);
  transform:translateX(14px);opacity:0;transition:transform .18s ease,opacity .18s ease;
}
.files-panel.on{transform:none;opacity:1;}
.files-hd{display:flex;align-items:center;gap:10px;padding:13px 16px;border-bottom:1px solid var(--line);}
.files-hd b{font-size:14px;color:var(--ink);}
.files-total{font-size:12px;color:var(--faint);}
.files-x{width:28px;height:28px;border:0;background:none;color:var(--faint);font-size:19px;line-height:1;
  border-radius:8px;cursor:pointer;}
.files-x:hover{background:var(--surface-2);color:var(--ink);}
.files-body{flex:1;min-height:0;display:grid;grid-template-columns:232px 1fr;}
.files-list{overflow:auto;border-right:1px solid var(--line);padding:8px;}
.file-item{display:block;width:100%;text-align:left;border:0;background:none;padding:9px 10px;
  border-radius:9px;cursor:pointer;transition:background .12s;}
.file-item:hover{background:var(--surface-2);}
.file-item.on{background:var(--brand-soft);}
.file-item b{display:block;font-size:13px;font-weight:600;color:var(--ink);line-height:1.45;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.file-item span{font-size:11.5px;color:var(--faint);}
.files-detail{overflow:auto;padding:18px 20px;}
.files-detail h3{margin:0 0 4px;font-size:16px;letter-spacing:-.01em;}
.files-meta{font-size:12px;color:var(--faint);margin-bottom:16px;}
.files-sec{margin-bottom:14px;}
.files-sec h4{margin:0 0 4px;font-size:11.5px;font-weight:600;color:var(--brand);letter-spacing:.04em;}
.files-sec p{margin:0;font-size:13px;line-height:1.75;white-space:pre-wrap;color:var(--text);}
.files-empty{margin:0;padding:16px;font-size:12.5px;color:var(--faint);line-height:1.7;}
.files-note{font-size:12px;color:var(--faint);}
.files-note.err{color:var(--bad);}
.files-ft{padding:10px 16px;border-top:1px solid var(--line);min-height:40px;}
@media (max-width:680px){
  .files-body{grid-template-columns:1fr;}
  .files-list{border-right:0;border-bottom:1px solid var(--line);max-height:36vh;}
}
"""

FILES_HTML = (
    '<div class="files-mask" id="filesMask" hidden></div>'
    '<aside class="files-panel" id="filesPanel" hidden role="dialog" aria-modal="true" aria-label="已存文件">'
    '<div class="files-hd"><b>文件</b><span class="files-total" id="filesTotal"></span>'
    '<span class="spacer"></span>'
    '<button class="btn ghost sm" id="filesExport" type="button">导出全部</button>'
    '<button class="files-x" id="filesClose" type="button" aria-label="关闭">×</button></div>'
    '<div class="files-body">'
    '<div class="files-list" id="filesList"></div>'
    '<div class="files-detail" id="filesDetail"><p class="files-empty">从左侧选一份文件。</p></div>'
    "</div>"
    '<div class="files-ft"><span class="files-note" id="filesBackup"></span></div>'
    "</aside>"
)

FILES_JS = """
(function(){
  var $=function(id){ return document.getElementById(id); };
  var panel=$('filesPanel'), mask=$('filesMask');
  if(!panel||!mask) return;

  function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function fmt(iso){
    var t=String(iso||'').slice(0,16).replace('T',' ');
    return t||'';
  }
  function req(path){
    return fetch(path,{headers:{'Accept':'application/json'}}).then(function(r){ return r.json(); });
  }
  function setBadge(n){
    n=Number(n)||0;
    var c=$('filesCount');
    if(c){ c.textContent=n>99?'99+':String(n); c.hidden=n<=0; }
    var t=$('filesTotal');
    if(t) t.textContent=n?('共 '+n+' 篇'):'';
  }

  function load(){
    var box=$('filesList');
    box.innerHTML='<p class="files-empty">加载中…</p>';
    req('/api/notes?limit=50').then(function(d){
      if(!d||!d.ok){ box.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      setBadge(d.count);
      var rows=d.items||[];
      if(!rows.length){
        box.innerHTML='<p class="files-empty">还没有文件。在问答里点「存为笔记」，或让智能体通过 MCP 保存。</p>';
        return;
      }
      box.innerHTML='';
      rows.forEach(function(it){
        var b=document.createElement('button');
        b.type='button'; b.className='file-item';
        b.setAttribute('data-id', it.id);
        b.innerHTML='<b>'+esc(it.title||'(无标题)')+'</b><span>'+esc(fmt(it.created))+'</span>';
        box.appendChild(b);
      });
      // 打开就直接读第一篇：让用户再点一次才看到内容，等于白给一步
      var first=box.querySelector('.file-item');
      if(first) first.click();
    }).catch(function(){
      box.innerHTML='<p class="files-empty">读取失败，检查服务是否还在运行。</p>';
    });
  }

  // 正文渲染只写一份：抽屉和 /files 页共用，两处各写一套迟早长歪
  function detailHtml(d){
    var meta=[fmt(d.created), d.kind||'', (d.tags||[]).join(' · ')].filter(Boolean).join(' · ');
    var html='<h3>'+esc(d.title||'(无标题)')+'</h3><div class="files-meta">'+esc(meta)+'</div>';
    var secs=(d.sections||[]).filter(function(s){ return s.body&&String(s.body).trim(); });
    if(!secs.length) html+='<p class="files-empty">这篇还没有正文。</p>';
    secs.forEach(function(s){
      html+='<div class="files-sec"><h4>'+esc(s.title)+'</h4><p>'+esc(s.body)+'</p></div>';
    });
    return html;
  }
  window.__notesDetailHtml=detailHtml;
  window.__notesFetch=req;

  function show(id, btn){
    [].forEach.call(panel.querySelectorAll('.file-item'), function(x){
      x.classList.toggle('on', x===btn);
    });
    var box=$('filesDetail');
    box.innerHTML='<p class="files-empty">读取中…</p>';
    req('/api/notes/'+encodeURIComponent(id)).then(function(d){
      if(!d||!d.ok){ box.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      box.innerHTML=detailHtml(d);
      box.scrollTop=0;
    }).catch(function(){
      box.innerHTML='<p class="files-empty">读取失败。</p>';
    });
  }

  // 红点属于「提醒」，不属于「数据」：点一下就该消失，且刷新后也别回来。
  // 用「上次导出时间」当签名——同一次未备份周期内只消一次，真导出过状态本来就会变。
  var DOT_KEY='rag_dot_off';
  function dotOff(){ try{ return localStorage.getItem(DOT_KEY)||''; }catch(e){ return ''; } }
  function dotSig(bk){ return String((bk&&bk.last_export_at)||'none'); }
  function renderBackup(bk){
    bk=bk||{};
    var dot=$('filesDot'), show=!!bk.due&&dotOff()!==dotSig(bk);
    if(dot){ dot.hidden=!show; dot.setAttribute('data-sig',dotSig(bk)); }
    if($('filesBackup')){
      $('filesBackup').textContent=bk.text?(bk.text+(bk.due?' · 建议导出一次':'')):'';
      $('filesBackup').className='files-note'+(bk.due?' err':'');
    }
  }
  // 设置面板也读同一份备份状态，红点的显示规则只能有一处，否则两边会打架
  window.__filesBackup=renderBackup;

  // 首屏与每次打开都同步一次数量/备份状态：存了新笔记再点进来，角标必须是最新的
  function refreshState(){
    fetch('/api/settings',{headers:{'Accept':'application/json'}}).then(function(r){ return r.json(); }).then(function(d){
      if(!d||!d.ok) return;
      setBadge(d.notes&&d.notes.count);
      renderBackup((d.notes&&d.notes.backup)||{});
    }).catch(function(){});
  }

  function open(){
    panel.hidden=false; mask.hidden=false;
    if($('filesBtn')) $('filesBtn').setAttribute('aria-expanded','true');
    document.body.classList.add('set-open');
    requestAnimationFrame(function(){ panel.classList.add('on'); });
    refreshState();
    load();
    var first=panel.querySelector('.file-item')||$('filesClose');
    if(first) first.focus();
  }
  function close(){
    panel.classList.remove('on');
    panel.hidden=true; mask.hidden=true;
    if($('filesBtn')) $('filesBtn').setAttribute('aria-expanded','false');
    document.body.classList.remove('set-open');
    if($('filesBtn')) $('filesBtn').focus();
  }

  // 问答页存完一篇就刷新角标：否则用户得刷新页面才看得到入口上的数字变了
  var prevSaved=window.__noteSaved;
  window.__noteSaved=function(d){
    if(typeof prevSaved==='function') prevSaved(d);
    refreshState();
  };

  if($('filesBtn')) $('filesBtn').addEventListener('click',open);
  if($('filesClose')) $('filesClose').addEventListener('click',close);
  mask.addEventListener('click',close);
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'&&!panel.hidden) close();
  });

  // 红点：点它只消提醒，不打开抽屉——「我知道了」和「我要看」是两个意图
  if($('filesDot')) $('filesDot').addEventListener('click',function(e){
    e.preventDefault(); e.stopPropagation();
    try{ localStorage.setItem(DOT_KEY, this.getAttribute('data-sig')||'none'); }catch(err){}
    this.hidden=true;
    if(window.toast) window.toast('备份提醒已消除');
  });

  // Ctrl/Cmd+Shift+F 开合文件面板；在输入框里不抢按键（那里常按组合键选词）
  document.addEventListener('keydown',function(e){
    if(!(e.ctrlKey||e.metaKey)||!e.shiftKey||(e.key||'').toLowerCase()!=='f') return;
    var tag=(document.activeElement||{}).tagName;
    if(tag==='INPUT'||tag==='TEXTAREA') return;
    e.preventDefault();
    if(panel.hidden) open(); else close();
  });

  // 位置再明确，也还是要有一次「它在这儿」的提示；每个浏览器只提示一次
  function showTip(){
    if(location.pathname.indexOf('/files')===0) return;   // 这一页本身全是文件，不用指路
    if(/[?&]notip=1/.test(location.search)) return;
    try{ if(localStorage.getItem('rag_files_tip')) return; }catch(e){ return; }
    var btn=$('filesBtn'); if(!btn||!btn.offsetParent) return;
    var tip=document.createElement('div');
    tip.className='files-tip';
    tip.innerHTML='已存文件都在这里 · <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd>';
    document.body.appendChild(tip);
    var r=btn.getBoundingClientRect();
    tip.style.top=(r.bottom+10)+'px';
    tip.style.right=Math.max(12, window.innerWidth-r.right-4)+'px';
    function done(){
      try{ localStorage.setItem('rag_files_tip','1'); }catch(e){}
      tip.remove();
    }
    setTimeout(done,7000);
    document.addEventListener('click',done,{once:true});
  }
  setTimeout(showTip,1200);
  if($('filesList')) $('filesList').addEventListener('click',function(e){
    var b=e.target.closest('.file-item'); if(!b) return;
    show(b.getAttribute('data-id'), b);
  });
  if($('filesExport')) $('filesExport').addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='导出中…';
    fetch('/api/notes/export?format=json').then(function(r){ return r.json(); }).then(function(d){
      if(!d||!d.ok){ if($('filesBackup')) $('filesBackup').textContent=(d&&d.message)||'导出失败'; return; }
      var blob=new Blob([d.content],{type:d.mime||'application/json;charset=utf-8'});
      var url=URL.createObjectURL(blob);
      var a=document.createElement('a');
      a.href=url; a.download=d.filename||'notes.json';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function(){ URL.revokeObjectURL(url); },1000);
      if($('filesBackup')){ $('filesBackup').textContent='已导出 '+(d.count||0)+' 篇'; $('filesBackup').className='files-note'; }
      if($('filesDot')) $('filesDot').hidden=true;
    }).catch(function(e){
      if($('filesBackup')) $('filesBackup').textContent='导出失败：'+((e&&e.message)||e);
    }).finally(function(){ btn.disabled=false; btn.textContent=label; });
  });

  // 首屏就把数量与备份状态读出来：入口上的角标不该等打开抽屉才出现
  refreshState();
})();
"""

# /files：不套抽屉的独立页。给「加不进 WorkBuddy 工具栏」这件事一个可直接收藏、
# 可直接被智能体打开的地址；抽屉那套仍留在两页里，用于不打断问答。
FILES_PAGE_HTML = (
    '<main class="pf-wrap">'
    '<div class="pf-head"><h1>文件</h1>'
    '<p class="pf-sub">已存的对话笔记，都是本地 Markdown。</p>'
    '<div class="pf-actions"><span class="pf-total" id="pfTotal"></span>'
    '<button class="btn sm" id="pfExport" type="button">导出全部</button></div></div>'
    '<div class="pf-grid">'
    '<div class="pf-list" id="pfList"></div>'
    '<div class="pf-detail" id="pfDetail"><p class="files-empty">从左侧选一份文件。</p></div>'
    "</div></main>"
)

FILES_PAGE_JS = """
(function(){
  var $=function(id){ return document.getElementById(id); };
  var list=$('pfList'); if(!list) return;
  function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function req(p){
    if(window.__notesFetch) return window.__notesFetch(p);
    return fetch(p,{headers:{'Accept':'application/json'}}).then(function(r){ return r.json(); });
  }
  function fmt(iso){ return String(iso||'').slice(0,16).replace('T',' '); }

  function load(){
    list.innerHTML='<p class="files-empty">加载中…</p>';
    req('/api/notes?limit=100').then(function(d){
      if(!d||!d.ok){ list.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      if($('pfTotal')) $('pfTotal').textContent='共 '+(d.count||0)+' 篇';
      var rows=d.items||[];
      if(!rows.length){
        list.innerHTML='<p class="files-empty">还没有文件。在问答里点「存为笔记」，或让智能体通过 MCP 保存。</p>';
        return;
      }
      list.innerHTML='';
      rows.forEach(function(it){
        var b=document.createElement('button');
        b.type='button'; b.className='file-item'; b.setAttribute('data-id',it.id);
        b.innerHTML='<b>'+esc(it.title||'(无标题)')+'</b><span>'+esc(fmt(it.created))+'</span>';
        list.appendChild(b);
      });
      var first=list.querySelector('.file-item'); if(first) first.click();
    }).catch(function(){
      list.innerHTML='<p class="files-empty">读取失败，检查服务是否还在运行。</p>';
    });
  }

  list.addEventListener('click',function(e){
    var b=e.target.closest('.file-item'); if(!b) return;
    [].forEach.call(list.querySelectorAll('.file-item'),function(x){ x.classList.toggle('on',x===b); });
    var box=$('pfDetail'); box.innerHTML='<p class="files-empty">读取中…</p>';
    req('/api/notes/'+encodeURIComponent(b.getAttribute('data-id'))).then(function(d){
      if(!d||!d.ok){ box.innerHTML='<p class="files-empty">'+esc((d&&d.message)||'读取失败')+'</p>'; return; }
      box.innerHTML=window.__notesDetailHtml?window.__notesDetailHtml(d):'';
      box.scrollTop=0;
    }).catch(function(){ box.innerHTML='<p class="files-empty">读取失败。</p>'; });
  });

  if($('pfExport')) $('pfExport').addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='导出中…';
    req('/api/notes/export?format=json').then(function(d){
      if(!d||!d.ok){ if(window.toast) window.toast((d&&d.message)||'导出失败',true); return; }
      var blob=new Blob([d.content],{type:d.mime||'application/json;charset=utf-8'});
      var url=URL.createObjectURL(blob), a=document.createElement('a');
      a.href=url; a.download=d.filename||'notes.json';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function(){ URL.revokeObjectURL(url); },1000);
      if(window.toast) window.toast('已导出 '+(d.count||0)+' 篇');
    }).catch(function(e){
      if(window.toast) window.toast('导出失败：'+((e&&e.message)||e),true);
    }).finally(function(){ btn.disabled=false; btn.textContent=label; });
  });

  load();
})();
"""

THEME_HEAD = (
    "<script>(function(){try{var s=localStorage.getItem('rag_theme');"
    "var t=(s==='dark'||s==='light')?s:(window.matchMedia&&"
    "window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');"
    "document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>"
)

SETTINGS_JS = """
(function(){
  var panel=document.getElementById('setPanel');
  if(!panel) return;
  var mask=document.getElementById('setMask');
  var gear=document.getElementById('setBtn');
  var tabs=document.getElementById('setTabs');
  var state={loaded:false, view:null};

  function $(id){ return document.getElementById(id); }
  // 转义统一用 JS_UTIL 里的那份：两处各写一套，改漏一处就是 XSS 缺口
  var esc=window.esc;
  function note(id,msg,bad){
    var el=$(id); if(!el) return;
    el.textContent=msg||'';
    el.className='set-note'+(msg?(bad?' err':' ok'):'');
  }
  // 更新结果里要放链接，textContent 装不下；进来的一律先转义
  function noteHtml(id,html,bad){
    var el=$(id); if(!el) return;
    el.innerHTML=html||'';
    el.className='set-note'+(html?(bad?' err':' ok'):'');
  }
  function outLink(href,text){
    if(!href) return '';
    return '<a href="'+esc(href)+'" target="_blank" rel="noopener">'+esc(text)+'</a>';
  }
  function api(method,path,body){
    var opt={method:method,headers:{'Content-Type':'application/json'}};
    if(body) opt.body=JSON.stringify(body);
    return fetch(path,opt).then(function(r){
      return r.json().catch(function(){ return {ok:false,message:'服务端返回了非 JSON 内容'}; });
    },function(){ return {ok:false,message:'连不上本地服务'}; });
  }

  function openPanel(){
    panel.hidden=false; if(mask) mask.hidden=false;
    document.body.classList.add('set-open');
    if(!state.loaded) load();
    var first=$('setBase');
    if(first) setTimeout(function(){ try{ first.focus(); }catch(e){} },60);
  }
  function closePanel(){
    panel.hidden=true; if(mask) mask.hidden=true;
    document.body.classList.remove('set-open');
  }
  if(gear) gear.addEventListener('click',openPanel);
  var closeBtn=$('setClose'); if(closeBtn) closeBtn.addEventListener('click',closePanel);
  if(mask) mask.addEventListener('click',closePanel);
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'&&!panel.hidden) closePanel();
  });

  function selectTab(name){
    if(!tabs) return;
    [].forEach.call(tabs.children,function(x){ x.classList.toggle('on',x.getAttribute('data-tab')===name); });
    [].forEach.call(panel.querySelectorAll('.set-pane'),function(p){
      p.classList.toggle('on',p.getAttribute('data-pane')===name);
    });
  }
  if(tabs) tabs.addEventListener('click',function(e){
    var btn=e.target.closest('button[data-tab]'); if(!btn) return;
    selectTab(btn.getAttribute('data-tab'));
  });
  // 页脚版本号点开就是「安装」分区：想看版本的人，下一个动作通常是查更新
  var footVer=$('footVer');
  if(footVer) footVer.addEventListener('click',function(){
    openPanel(); selectTab('install');
  });

  function segHome(which){
    var seg=$('setHomeSeg'); if(!seg) return;
    [].forEach.call(seg.children,function(b){ b.classList.toggle('on',b.getAttribute('data-home')===which); });
    var wrap=$('setHomeWrap'); if(wrap) wrap.hidden=(which!=='custom');
  }

  function renderBackup(bk){
    bk=bk||{};
    // 红点规则收在 FILES_JS 里（含「点过就消」的本地标记），这里只转发，避免两处各判一次
    if(window.__filesBackup){ window.__filesBackup(bk); return; }
    if($('filesBackup')){
      $('filesBackup').textContent=bk.text?(bk.text+(bk.due?' · 建议导出一次':'')):'';
      $('filesBackup').className='files-note'+(bk.due?' err':'');
    }
  }

  function refreshBackup(){
    // 只刷红点与文案，不碰用户正在填的输入框——存完笔记立刻看到提醒才有意义
    api('GET','/api/settings').then(function(d){
      if(d&&d.ok) renderBackup(d.notes&&d.notes.backup);
    });
  }

  function applyView(d){
    state.view=d; state.loaded=true;
    if($('setCfgWarn')){
      // 配置写坏时界面显示的是默认值，必须说清楚，否则用户以为密钥自己没了
      var cfgWarn=d.config_error
        ? ('配置文件无法解析（'+d.config_error+'），下面显示的是默认值；修好后重新打开面板')
        : (d.config_backup ? ('原配置无法解析，保存前已备份到 '+d.config_backup) : '');
      $('setCfgWarn').hidden=!cfgWarn;
      $('setCfgWarn').textContent=cfgWarn;
    }
    // 输入框填「配置值」，没配过就填当前生效值：否则空表单点保存会被校验拦下（配置写坏时直接死锁）
    if($('setBase')){ $('setBase').value=d.llm.base_url||d.llm.effective_base_url||''; $('setBase').placeholder=d.llm.base_url_default||''; }
    if($('setModel')){ $('setModel').value=d.llm.model||d.llm.effective_model||''; $('setModel').placeholder=d.llm.model_default||''; }
    if($('setKey')){
      $('setKey').value='';
      $('setKey').placeholder=d.llm.api_key_set
        ? ('已保存 '+d.llm.api_key_masked+'，留空不改')
        : '粘贴密钥';
    }
    note('setApiNote', d.llm.key_ready
      ? ('当前生效：'+(d.llm.effective_model||'')+' @ '+(d.llm.effective_base_url||''))
      : '还没配密钥，问答会走本地抽取，不调用模型', !d.llm.key_ready);

    segHome(d.notes.home?'custom':'default');
    if($('setHome')) $('setHome').value=d.notes.home||'';
    note('setHomeNote', d.notes.home_effective
      ? ('当前生效：'+d.notes.home_effective)
      : '当前生效：默认位置', !!d.notes.error);

    var mig=$('setMigrate');
    if(mig){
      var pending=d.pending_migration;
      if(pending&&pending.count){
        mig.hidden=false;
        mig.setAttribute('data-from',pending.from||'');
        if($('setMigrateText')) $('setMigrateText').textContent=
          '原位置还有 '+pending.count+' 篇笔记，要复制到新位置吗？';
      } else {
        mig.hidden=true;
        mig.removeAttribute('data-from');
      }
    }

    var bk=(d.notes&&d.notes.backup)||{};
    renderBackup(bk);

    if($('setStoreChat')) $('setStoreChat').checked=!!d.notes.store_chat;
    window.__storeChat=!!d.notes.store_chat;
    try{ document.dispatchEvent(new CustomEvent('storechat:change',{detail:window.__storeChat})); }catch(e){}

    var dl=d.downloads||{};
    var page=(d.repo_url||'')+'/releases/latest';
    if($('setDownload')) $('setDownload').href=dl.app||page;
    if($('setDownloadPlugin')) $('setDownloadPlugin').href=dl.plugin||page;
    if($('setMcpPre')) $('setMcpPre').textContent=JSON.stringify(d.mcp||{},null,2);
  }

  function load(){
    api('GET','/api/settings').then(function(d){
      if(!d||!d.ok){ note('setApiNote',(d&&d.message)||'读取设置失败',true); return; }
      applyView(d);
    });
  }

  if($('setSave')) $('setSave').addEventListener('click',function(){
    var body={llm:{base_url:$('setBase').value.trim(),model:$('setModel').value.trim()}};
    var key=$('setKey').value.trim();
    if(key) body.llm.api_key=key;
    note('setApiNote','保存中…',false);
    api('POST','/api/settings',body).then(function(d){
      if(!d||!d.ok){ note('setApiNote',(d&&d.message)||'保存失败',true); return; }
      applyView(d);
      note('setApiNote','已保存，下一次提问就用新配置',false);
    });
  });

  if($('setTest')) $('setTest').addEventListener('click',function(){
    note('setApiNote','测试中（最多等 15 秒）…',false);
    api('POST','/api/settings/test',{
      base_url:$('setBase').value.trim(),
      model:$('setModel').value.trim(),
      api_key:$('setKey').value.trim()
    }).then(function(d){
      if(!d||!d.ok){ note('setApiNote',(d&&d.message)||'测试失败',true); return; }
      note('setApiNote','连接正常，往返 '+d.latency_ms+' ms',false);
    });
  });

  // 检查更新：只读一次 GitHub 的 latest Release，不下载、不落盘、不改配置。
  // 离线、被代理拦、仓库没发过 Release 都要说清楚是哪一种，而不是笼统地「失败」。
  if($('setUpdate')) $('setUpdate').addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='检查中…';
    note('setUpdateNote','正在查 GitHub…','');
    api('GET','/api/update/check?force=1').then(function(d){
      if(!d||!d.ok){
        var url=(d&&d.url)||'';
        noteHtml('setUpdateNote',esc((d&&d.message)||'检查失败')
          +(url?' · '+outLink(url,'打开发布页'):''),true);
        return;
      }
      if(!d.has_update){
        noteHtml('setUpdateNote','已是最新：v'+esc(d.latest)+'（本地 v'+esc(d.current)+'）');
        return;
      }
      var dl=d.downloads||{};
      var links=[outLink(dl.app,'下载应用包'),outLink(dl.plugin,'下载插件包'),
                 outLink(d.url,'更新说明')].filter(Boolean).join(' · ');
      noteHtml('setUpdateNote','发现新版本 v'+esc(d.latest)
        +(d.published_at?'（'+esc(d.published_at)+'）':'')+'：'+links);
    }).catch(function(e){
      note('setUpdateNote','检查失败：'+((e&&e.message)||e),true);
    }).finally(function(){ btn.disabled=false; btn.textContent=label; });
  });

  if($('setHomeSeg')) $('setHomeSeg').addEventListener('click',function(e){
    var btn=e.target.closest('button[data-home]'); if(!btn) return;
    segHome(btn.getAttribute('data-home'));
    if(btn.getAttribute('data-home')==='custom'&&$('setHome')) $('setHome').focus();
  });

  function applyHome(home){
    note('setHomeNote','切换中…',false);
    return api('POST','/api/settings',{notes:{home:home}}).then(function(d){
      if(!d||!d.ok){ note('setHomeNote',(d&&d.message)||'切换失败',true); return d; }
      applyView(d);
      note('setHomeNote','已切换：'+(d.notes.home_effective||''),false);
      if(window.__afterHomeChange) window.__afterHomeChange();
      return d;
    });
  }

  if($('setHomeSave')) $('setHomeSave').addEventListener('click',function(){
    var seg=$('setHomeSeg').querySelector('button.on');
    var custom=seg&&seg.getAttribute('data-home')==='custom';
    var home=custom?$('setHome').value.trim():'';
    if(custom&&!home){ note('setHomeNote','先填一个目录，或用「默认位置」',true); return; }
    applyHome(home);
  });

  if($('setPick')) $('setPick').addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='等待选择…';
    note('setHomeNote','已弹出系统窗口，选好目录会自动应用',false);
    api('POST','/api/settings/pick-folder',{}).then(function(d){
      btn.disabled=false; btn.textContent=label;
      if(!d||!d.ok){
        var kind=d&&d.error;
        note('setHomeNote', kind==='cancelled' ? '已取消'
          : ((d&&d.message)||'选择失败，请手动填路径'), !(kind==='cancelled'));
        return;
      }
      segHome('custom');
      if($('setHome')) $('setHome').value=d.path;
      // 选中即应用：对话框本身就是一次确认，再要求点「应用」是多余的一步
      applyHome(d.path);
    },function(){
      btn.disabled=false; btn.textContent=label;
      note('setHomeNote','请求超时，请手动填路径',true);
    });
  });

  if($('setMigrateGo')) $('setMigrateGo').addEventListener('click',function(){
    var mig=$('setMigrate');
    var from=mig&&mig.getAttribute('data-from');
    if(!from){ if(mig) mig.hidden=true; return; }
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='复制中…';
    api('POST','/api/settings/notes/migrate',{from:from}).then(function(d){
      btn.disabled=false; btn.textContent=label;
      if(!d||!d.ok){ note('setHomeNote',(d&&d.message)||'复制失败',true); return; }
      if(mig) mig.hidden=true;
      var msg='已复制 '+d.copied+' 篇';
      if(d.skipped) msg+='，跳过 '+d.skipped+' 篇同名';
      if(d.failed&&d.failed.length) msg+='，失败 '+d.failed.length+' 篇';
      note('setHomeNote',msg,!!(d.failed&&d.failed.length));
      if(window.__afterHomeChange) window.__afterHomeChange();
    });
  });

  if($('setMigrateNo')) $('setMigrateNo').addEventListener('click',function(){
    var mig=$('setMigrate'); if(mig) mig.hidden=true;
  });

  if($('setOpen')) $('setOpen').addEventListener('click',function(){
    api('POST','/api/settings/open',{}).then(function(d){
      if(!d||!d.ok) note('setHomeNote',(d&&d.message)||'打不开文件夹',true);
    });
  });

  if($('setStoreChat')) $('setStoreChat').addEventListener('change',function(){
    var on=this.checked;
    api('POST','/api/settings',{notes:{store_chat:on}}).then(function(d){
      if(!d||!d.ok){
        $('setStoreChat').checked=!on;
        note('setChatNote',(d&&d.message)||'保存失败',true);
        return;
      }
      window.__storeChat=on;
      note('setChatNote', on
        ? '已开启：问答里会出现「存为笔记」'
        : '已关闭：不再写入任何对话内容，已有笔记不受影响', false);
      try{ document.dispatchEvent(new CustomEvent('storechat:change',{detail:on})); }catch(e){}
    });
  });

  if($('setMcpCopy')) $('setMcpCopy').addEventListener('click',function(){
    var text=$('setMcpPre')?$('setMcpPre').textContent:'';
    function done(){ note('setMcpNote','已复制，粘贴到客户端的 mcpServers 里',false); }
    function fail(){ note('setMcpNote','复制失败，请手动选中复制',true); }
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(done,fail);
    } else { fail(); }
  });

  if($('setMcpInstall')) $('setMcpInstall').addEventListener('click',function(){
    if(!confirm('会写入 Claude Desktop 的配置，原文件先备份。继续？')) return;
    api('POST','/api/settings/mcp/install',{}).then(function(d){
      if(!d||!d.ok){ note('setMcpNote',(d&&d.message)||'写入失败',true); return; }
      note('setMcpNote',d.message+'（'+d.target+'）',false);
    });
  });

  // 每页加载都先拉一次：问答页要靠 store_chat 决定「存为笔记」是否出现，
  // 不能等用户打开设置面板才拿到状态。
  load();
})();
"""

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

// 页面一加载就同步「储存对话内容」开关。
// 之前只在打开设置抽屉时才知道开关状态：开关明明是开的，「存为笔记」也要先点一次设置才出现，
// 用户会以为功能坏了（e2e 在干净环境里也正因此超时）。
(function(){
  if(!window.fetch) return;
  fetch('/api/settings').then(function(r){ return r.json(); }).then(function(d){
    if(d&&d.ok){ window.__storeChat=!!d.notes.store_chat; }
  }).catch(function(){});
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
        f"<title>{title}</title><style>{BASE_CSS}{SETTINGS_CSS}{FILES_CSS}{css}</style></head><body>"
        f"{nav(active)}{body}{footer()}"
        f"{FILES_HTML}{SETTINGS_HTML}"
        f'<div id="toasts"></div><script>{script}</script>'
        f"<script>{FILES_JS}</script>"
        f"<script>{SETTINGS_JS}</script><script>{THEME_JS}</script></body></html>"
    )


# 供页面脚本复用的小工具：转义、toast
JS_UTIL = """
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function ragApiKey(){ try{ return sessionStorage.getItem('rag_api_key')||''; }catch(e){ return ''; } }
function apiHeaders(base){
  var h=base||{}, k=ragApiKey();
  if(k) h['X-API-Key']=k;
  return h;
}
function toast(msg,isErr){
  var box=document.getElementById('toasts'); if(!box) return;
  var d=document.createElement('div'); d.className='toast'+(isErr?' err':'');
  d.innerHTML='<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="'+((isErr)?'M18 6 6 18M6 6l12 12':'m20 6-11 11-5-5')+'"/></svg><span></span>';
  d.querySelector('span').textContent=msg||'';
  box.appendChild(d);
  setTimeout(function(){ d.style.transition='opacity .25s, transform .25s'; d.style.opacity='0'; d.style.transform='translateY(6px)'; setTimeout(function(){d.remove();},260); }, 2600);
}
"""


# 独立文件页：`/files` 直接用，不必先打开抽屉
FILES_PAGE = shell("files", f"文件 · {BRAND}", FILES_PAGE_HTML, FILES_PAGE_JS)
