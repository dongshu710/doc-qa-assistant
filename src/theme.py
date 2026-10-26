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
    "chat": '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9.6 9.6 0 0 1-3.8-.8L3 21l1.9-4.6A8.4 8.4 0 0 1 12 3a8.4 8.4 0 0 1 9 8.5z"/>',
    "folder": '<path d="M3 7.5A2 2 0 0 1 5 5.5h4l2 2.5h8a2 2 0 0 1 2 2v6.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "panel": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
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
  /* 左栏用比主区深一档的中性灰，这是 DeepSeek 界面里唯一的分层手段 */
  --side-bg:#f9f9f9; --side-line:#ededed; --hover:#efefef;
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

/* ============ 应用外壳 ============
   参照 DeepSeek 的三段式：左侧常驻会话栏、中间对话流、底部输入。
   左栏宽度固定 260px，收起后 60px 只留图标；主区纯白，靠留白分层，不靠卡片阴影。 */
.app{display:flex;min-height:100vh;width:100%;}
.side{
  position:sticky;top:0;z-index:60;flex:none;width:260px;height:100vh;
  display:flex;flex-direction:column;padding:8px 8px 6px;
  background:var(--side-bg);border-right:1px solid var(--side-line);
  transition:width .18s ease;
}
.side-head{display:flex;align-items:center;gap:6px;height:44px;padding:0 6px 0 2px;}
.brand{display:flex;align-items:center;gap:9px;min-width:0;flex:1;padding:4px 6px;border-radius:8px;}
.brand:hover{background:var(--hover);}
.mark{
  width:26px;height:26px;border-radius:8px;flex:none;color:#fff;
  background:var(--brand);display:flex;align-items:center;justify-content:center;
}
.mark svg{width:16px;height:16px;}
.brand-text{display:flex;align-items:center;min-width:0;}
.brand-text b{font-size:14px;font-weight:600;color:var(--ink);letter-spacing:-.01em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.side-mini-btn{
  flex:none;width:28px;height:28px;border-radius:7px;border:0;background:transparent;
  color:var(--faint);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;
}
.side-mini-btn:hover{background:var(--hover);color:var(--ink);}
.new-chat{
  display:flex;align-items:center;gap:8px;width:100%;height:38px;margin:2px 0 6px;
  padding:0 10px;border:1px solid var(--side-line);border-radius:10px;
  background:var(--surface);color:var(--ink);font-size:13.5px;font-weight:500;cursor:pointer;
  transition:background .14s,border-color .14s;
}
.new-chat:hover{border-color:#d7d7d7;background:var(--surface);}
.new-chat svg{flex:none;color:var(--text);}
.new-chat kbd{
  margin-left:auto;font:10.5px var(--mono);color:var(--faint);
  background:var(--side-bg);border:1px solid var(--side-line);border-radius:5px;padding:1px 4px;
}
.side-search{position:relative;display:flex;align-items:center;margin-bottom:4px;}
.side-search svg{position:absolute;left:9px;color:var(--faint);pointer-events:none;}
.side-search input{
  width:100%;height:32px;padding:0 8px 0 29px;border:1px solid transparent;border-radius:8px;
  background:transparent;color:var(--text);font-size:13px;
}
.side-search input::placeholder{color:var(--faint);}
.side-search input:hover{background:var(--hover);}
.side-search input:focus{outline:none;background:var(--surface);border-color:var(--line-2);}
.side-scroll{flex:1;min-height:0;overflow-y:auto;overflow-x:hidden;padding:2px 0 6px;}
.side-scroll::-webkit-scrollbar{width:6px;}
.side-scroll::-webkit-scrollbar-thumb{background:#dcdcdc;border-radius:3px;}
.conv-group{margin:10px 8px 4px;font-size:11px;font-weight:600;letter-spacing:.04em;color:#9b9b9b;}
.conv{
  display:flex;align-items:center;gap:6px;width:100%;height:34px;padding:0 8px;
  border:0;border-radius:8px;background:transparent;color:var(--text);
  font-size:13px;line-height:1.4;text-align:left;cursor:pointer;
}
.conv .t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.conv:hover{background:var(--hover);}
.conv.on{background:#e9e9e9;font-weight:500;}
.conv .x{
  flex:none;width:20px;height:20px;border:0;border-radius:5px;background:transparent;
  color:var(--faint);font-size:14px;line-height:1;cursor:pointer;opacity:0;
}
.conv:hover .x,.conv.on .x{opacity:1;}
.conv .x:hover{background:#dcdcdc;color:var(--ink);}
.side-empty{padding:18px 10px;font-size:12.5px;color:var(--faint);line-height:1.7;}
.side-empty a{color:var(--brand);}
.side-foot{flex:none;border-top:1px solid var(--side-line);padding-top:6px;display:flex;flex-direction:column;gap:1px;}
.sb-wrap{position:relative;}
.sb-item{
  display:flex;align-items:center;gap:9px;width:100%;height:36px;padding:0 8px;
  border:0;border-radius:8px;background:transparent;color:var(--text);
  font-size:13px;text-align:left;cursor:pointer;text-decoration:none;
}
.sb-item:hover{background:var(--hover);color:var(--ink);}
.sb-item.active{background:var(--hover);color:var(--ink);font-weight:500;}
.sb-item.active svg{color:var(--ink);}
.sb-item svg{flex:none;color:var(--faint);}
.sb-item:hover svg{color:var(--text);}
.sb-item .sb-label{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.sb-item .nf-count{
  min-width:17px;height:17px;padding:0 4px;border-radius:999px;background:#e4e4e4;
  color:#666;font-size:10.5px;font-weight:600;line-height:17px;text-align:center;
}
.sb-item .nf-count[hidden]{display:none;}
.side-meta{display:flex;align-items:center;gap:2px;padding:4px 2px 2px;}
.side-meta .foot-ver{margin-left:2px;}
.side-meta .spacer{flex:1;}
.icon-btn{
  flex:none;width:30px;height:30px;border:0;border-radius:7px;background:transparent;
  color:var(--faint);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;
}
.icon-btn:hover{background:var(--hover);color:var(--ink);}
/* 收起态：只留图标，标题与快捷键隐藏 */
body.side-mini .side{width:64px;padding-left:6px;padding-right:6px;}
body.side-mini .brand,
body.side-mini .new-chat kbd,
body.side-mini .new-chat .nc-label,
body.side-mini .side-search,
body.side-mini .side-scroll,
body.side-mini .sb-item .sb-label,
body.side-mini .sb-item .nf-count,
body.side-mini .side-meta .foot-ver{display:none;}
/* 收起后必须留一个「展开」入口：把它一起藏掉，用户就只能刷新页面 */
body.side-mini .side-mini-btn{display:inline-flex;}
body.side-mini .new-chat{justify-content:center;padding:0;border-color:transparent;background:transparent;}
body.side-mini .new-chat:hover{background:var(--hover);}
body.side-mini .side-head{justify-content:center;padding:0;}
body.side-mini .sb-item{justify-content:center;padding:0;}
/* 主区 */
.main{flex:1;min-width:0;display:flex;flex-direction:column;height:100vh;background:var(--surface);}
.stage{flex:1;min-height:0;display:flex;flex-direction:column;overflow:auto;}
.topbar{
  flex:none;display:flex;align-items:center;gap:8px;height:52px;padding:0 14px 0 18px;
  border-bottom:1px solid transparent;
}
.topbar .tb-title{
  font-size:13.5px;font-weight:600;color:var(--ink);max-width:min(52vw,520px);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.topbar .tb-sub{font-size:12px;color:var(--faint);white-space:nowrap;}
.topbar .tb-actions{margin-left:auto;display:flex;align-items:center;gap:2px;}
.tb-link{
  height:30px;padding:0 9px;border:0;border-radius:7px;background:transparent;
  color:var(--muted);font-size:12.5px;cursor:pointer;
}
.tb-link:hover{background:var(--surface-2);color:var(--ink);}
.side-scrim{display:none;}
.mnav{display:none;position:fixed;top:10px;left:10px;z-index:70;}
@media (max-width:900px){
  .stage-ask .topbar{padding-left:50px;}
  .stage-kb .wrap,.stage-files .wrap{padding-top:44px;}
}
@media (max-width:900px){
  .side{
    position:fixed;left:0;top:0;z-index:95;width:min(82vw,300px);
    transform:translateX(-100%);transition:transform .2s ease;box-shadow:0 0 40px rgba(0,0,0,.16);
  }
  body.side-open .side{transform:none;}
  .side-scrim{
    display:block;position:fixed;inset:0;z-index:90;background:rgba(17,17,17,.34);
    opacity:0;pointer-events:none;transition:opacity .18s ease;
  }
  body.side-open .side-scrim{opacity:1;pointer-events:auto;}
  body.side-mini .side{width:min(82vw,300px);padding:8px 8px 6px;}
  body.side-mini .brand-text,body.side-mini .side-search,body.side-mini .side-scroll,
  body.side-mini .sb-item .sb-label,body.side-mini .sb-item .nf-count,
  body.side-mini .side-meta .foot-ver,body.side-mini .new-chat kbd{display:revert;}
  body.side-mini .side-head{justify-content:flex-start;padding:0 6px 0 2px;}
  body.side-mini .sb-item{justify-content:flex-start;padding:0 8px;}
  body.side-mini .new-chat{justify-content:flex-start;padding:0 10px;border-color:var(--side-line);}
  .main{height:auto;min-height:100vh;}
  .stage{overflow:visible;}
  .mnav{
    display:inline-flex;align-items:center;justify-content:center;flex:none;
    width:32px;height:32px;border:0;border-radius:8px;background:transparent;color:var(--text);cursor:pointer;
  }
  .mnav:hover{background:var(--surface-2);}
}
@media (max-width:640px){
  /* iOS Safari 在输入框字号 <16px 时会强制放大页面，表现为「点一下界面就变大」 */
  input,textarea,select{font-size:16px;}
}
.theme-toggle{
  flex:none;width:30px;height:30px;border-radius:7px;cursor:pointer;
  display:inline-flex;align-items:center;justify-content:center;
  border:0;background:transparent;color:var(--faint);
}
.theme-toggle:hover{background:var(--hover);color:var(--ink);}
.theme-toggle .ic-sun{display:none;}
[data-theme="dark"] .theme-toggle .ic-sun{display:inline-flex;}
[data-theme="dark"] .theme-toggle .ic-moon{display:none;}
/* 已存红点：独立按钮，点它只消提醒 */
.files-dot{
  position:absolute;top:11px;right:32px;width:14px;height:14px;padding:0;border:0;
  background:transparent;cursor:pointer;z-index:2;
}
.files-dot::after{
  content:"";display:block;width:7px;height:7px;margin:0 auto;border-radius:50%;
  background:var(--bad);box-shadow:0 0 0 2px var(--side-bg);
}
.files-dot[hidden]{display:none;}

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
  --bg:#17181c; --surface:#202126; --surface-2:#26272c;
  --side-bg:#17181c; --side-line:#2d2e34; --hover:#26272c;
  --brand:#7c93ff; --brand-600:#93a6ff; --brand-2:#7c93ff; --brand-soft:#262b44; --brand-tint:#1f2130;
  --ok:#34d399; --ok-soft:#0f2f26; --warn:#fbbf24; --warn-soft:#33260c; --bad:#f87171; --bad-soft:#3a1518;
  --sh-1:0 1px 2px rgba(0,0,0,.45); --sh-2:0 12px 32px -18px rgba(0,0,0,.85);
  --sh-3:0 30px 70px -30px rgba(0,0,0,.9);
}
[data-theme="dark"] ::selection{background:#2f3a63;color:#eef2ff;}
[data-theme="dark"] code{background:#232429;border-color:var(--line);color:#c9ccd4;}
[data-theme="dark"] .site-foot{background:var(--surface);}
[data-theme="dark"] .conv.on{background:#2f3036;}
[data-theme="dark"] .conv .x:hover{background:#3a3b42;}
[data-theme="dark"] .sb-item .nf-count{background:#33343a;color:#b9bcc4;}
[data-theme="dark"] .new-chat{background:transparent;}
[data-theme="dark"] .new-chat:hover{border-color:#3a3b42;}
[data-theme="dark"] .side-search input:focus{background:#26272c;}
[data-theme="dark"] .files-dot::after{box-shadow:0 0 0 2px var(--side-bg);}
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
    """左侧常驻栏：会话列表 + 底部三个入口。

    位置参照 DeepSeek：新建对话在最上、历史居中滚动、设置在最下。
    差别只有一处——这里还要挂「文件」抽屉，所以底部是三行而不是一处头像。
    """
    def nav_item(key: str, href: str, label: str, glyph: str) -> str:
        on = " active" if key == active else ""
        return (f'<a class="sb-item{on}" href="{href}" data-nav="{key}">'
                f'{icon(glyph, 17)}<span class="sb-label">{label}</span></a>')

    nav_html = nav_item("kb", "/kb", "知识库", "doc") if links else ""
    return (
        '<aside class="side" id="sideBar" aria-label="会话与导航">'
        '<div class="side-head">'
        f'<a class="brand" href="/ask">{MARK}<span class="brand-text"><b>{BRAND}</b></span></a>'
        '<button class="side-mini-btn" id="sideMini" type="button" aria-label="收起侧栏" title="收起侧栏">'
        + icon("panel", 16) +
        '</button></div>'
        '<button class="new-chat" id="newChat" type="button" title="新对话 · Ctrl+K">'
        + icon("plus", 16) + '<span class="nc-label">新对话</span><kbd>Ctrl K</kbd></button>'
        '<div class="side-search">' + icon("search", 14) +
        '<input id="convSearch" type="search" placeholder="搜索对话" aria-label="搜索对话" autocomplete="off"></div>'
        '<div class="side-scroll"><div class="conv-list" id="convList"></div></div>'
        '<div class="side-foot">'
        # 文件：常驻入口，点开抽屉；红点是独立按钮，只消提醒
        '<div class="sb-wrap">'
        f'<button class="sb-item{" active" if active == "files" else ""}" id="filesBtn" type="button" aria-haspopup="dialog" '
        'aria-controls="filesPanel" aria-expanded="false" aria-keyshortcuts="Control+Shift+F" '
        'title="已存文件 · Ctrl+Shift+F">'
        + icon("folder", 17) + '<span class="sb-label">文件</span>'
        '<span class="nf-count" id="filesCount" hidden>0</span></button>'
        '<button class="files-dot" id="filesDot" type="button" aria-label="消除备份提醒" '
        'title="点一下消除提醒" hidden></button>'
        '</div>'
        + nav_html +
        '<button class="sb-item" id="setBtn" type="button">'
        + icon("gear", 17) + '<span class="sb-label">设置</span></button>'
        '<div class="side-meta">'
        f'<button class="foot-ver" id="footVer" type="button" title="版本与更新">v{__version__}</button>'
        '<span class="spacer"></span>'
        '<button class="theme-toggle" id="themeToggle" type="button" aria-label="切换深色模式" title="切换深色模式">'
        f'<span class="ic-moon">{icon("moon", 15)}</span>'
        f'<span class="ic-sun">{icon("sun", 15)}</span></button>'
        '</div></div></aside>'
        '<div class="side-scrim" id="sideScrim" hidden></div>'
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


SIDE_JS = """
/* ============ 会话列表（本地存储） ============
   为什么放浏览器：这些对话只是「看过的记录」，不是要长期保存的资料；
   真正要留的东西走「存为笔记」，落在磁盘上的 Markdown 里。
   两条存储各管一件事，用户才不会以为清了会话就丢了笔记。 */
(function(){
  var KEY='jy_threads_v1', LEGACY='rag_history_v1', MAX=60;
  function now(){ return new Date().toISOString(); }
  function uid(){ return 't'+Date.now().toString(36)+Math.random().toString(36).slice(2,6); }
  function titleOf(q){
    var t=String(q||'').replace(/\\s+/g,' ').trim();
    return t?t.slice(0,28):'新对话';
  }
  function read(){
    try{
      var raw=localStorage.getItem(KEY); var d=raw?JSON.parse(raw):null;
      if(d&&Array.isArray(d.threads)) return d;
    }catch(e){}
    return null;
  }
  function write(d){ try{ localStorage.setItem(KEY,JSON.stringify(d)); }catch(e){} }
  function migrate(){
    // 老版本只有一条「当前对话」的流水，升级后包成一条会话，历史不丢
    try{
      var raw=localStorage.getItem(LEGACY); if(!raw) return null;
      var rows=JSON.parse(raw); if(!Array.isArray(rows)||!rows.length) return null;
      var id=uid();
      var t={id:id,title:titleOf(rows[0]&&rows[0].q),
             created:(rows[0]&&rows[0].ts)||now(),
             updated:((rows[rows.length-1]||{}).ts)||now(),turns:rows};
      var d={v:1,current:id,threads:[t]};
      write(d); return d;
    }catch(e){ return null; }
  }
  function ensure(){
    var d=read()||migrate();
    if(!d){ d={v:1,current:'',threads:[]}; }
    if(!Array.isArray(d.threads)) d.threads=[];
    return d;
  }
  function pick(d){
    if(!d) return null;
    for(var i=0;i<d.threads.length;i++){ if(d.threads[i].id===d.current) return d.threads[i]; }
    return null;
  }
  function currentThread(){ return pick(ensure()); }
  function fmt(iso){
    var d=new Date(iso||'');
    if(isNaN(d.getTime())) return '';
    function p(n){ return (n<10?'0':'')+n; }
    return (d.getMonth()+1)+'月'+d.getDate()+'日 '+p(d.getHours())+':'+p(d.getMinutes());
  }
  function group(iso){
    var d=new Date(iso||''), t=new Date();
    if(isNaN(d.getTime())) return '更早';
    var a=new Date(t.getFullYear(),t.getMonth(),t.getDate()).getTime();
    var b=new Date(d.getFullYear(),d.getMonth(),d.getDate()).getTime();
    var days=Math.round((a-b)/86400000);
    if(days<=0) return '今天';
    if(days===1) return '昨天';
    if(days<7) return '7 天内';
    return '更早';
  }
  var ORDER=['今天','昨天','7 天内','更早'];

  var JY={
    key:KEY,
    list:function(){
      return ensure().threads.slice().sort(function(a,b){
        return String(b.updated||'').localeCompare(String(a.updated||''));
      });
    },
    currentId:function(){ return ensure().current; },
    currentThread:currentThread,
    create:function(){
      var d=ensure(); var t={id:uid(),title:'新对话',created:now(),updated:now(),turns:[]};
      d.threads.unshift(t); d.current=t.id;
      d.threads=d.threads.slice(0,MAX);
      write(d); JY.render(); return t;
    },
    open:function(id){
      var d=ensure();
      for(var i=0;i<d.threads.length;i++){
        if(d.threads[i].id===id){ d.current=id; write(d); JY.render(); return d.threads[i]; }
      }
      return null;
    },
    append:function(turn){
      // 必须用同一个 d 找当前会话：ensure() 每次都会重新解析 JSON，
      // 再调一次 currentThread() 拿到的是另一份副本，改了也写不回同一个对象。
      var d=ensure(); var t=pick(d);
      if(!t){ t={id:uid(),title:titleOf(turn&&turn.q),created:now(),updated:now(),turns:[]};
        d.threads.unshift(t); d.current=t.id; }
      t.turns.push(turn);
      if(t.title==='新对话'||!t.title) t.title=titleOf(turn&&turn.q);
      t.updated=now();
      var i=d.threads.indexOf(t);
      if(i>0){ d.threads.splice(i,1); d.threads.unshift(t); }
      write(d); JY.render();
      return t;
    },
    touch:function(patch){
      var d=ensure(); var t=pick(d); if(!t) return null;
      Object.assign(t,patch||{}); t.updated=now(); write(d); JY.render(); return t;
    },
    remove:function(id){
      var d=ensure();
      d.threads=d.threads.filter(function(t){ return t.id!==id; });
      if(d.current===id) d.current=(d.threads[0]||{}).id||'';
      write(d); JY.render();
    },
    clearCurrent:function(){
      var d=ensure(); var t=pick(d); if(!t) return null;
      t.turns=[]; t.title='新对话'; t.updated=now(); write(d); JY.render(); return t;
    },
    render:function(){
      var box=document.getElementById('convList'); if(!box) return;
      var q=(document.getElementById('convSearch')||{}).value||'';
      q=q.trim().toLowerCase();
      var rows=JY.list().filter(function(t){
        return !q||String(t.title||'').toLowerCase().indexOf(q)>=0;
      });
      var html='', last='';
      rows.forEach(function(t){
        var g=group(t.updated);
        if(g!==last){ html+='<div class="conv-group">'+g+'</div>'; last=g; }
        var on=t.id===JY.currentId()?' on':'';
        html+='<button type="button" class="conv'+on+'" data-id="'+t.id+'" title="'+esc(t.title||'')+'">'
          +'<span class="t">'+esc(t.title||'新对话')+'</span>'
          +'<span class="x" data-del="'+t.id+'" role="button" aria-label="删除这条会话">×</span></button>';
      });
      if(!rows.length){
        html='<div class="side-empty">'+(q?'没有匹配的对话。':'还没有对话记录。直接在下面提问就会出现在这里。')+'</div>';
      }
      box.innerHTML=html;
    }
  };
  window.JY=JY;

  // ---------- 侧栏交互 ----------
  function el(id){ return document.getElementById(id); }
  // 遮罩带 hidden 属性（桌面端不该占位），打开时要真去掉，否则点不到
  window.__closeSide=closeSide;
  function openSide(){
    document.body.classList.add('side-open');
    var s=el('sideScrim'); if(s) s.hidden=false;
  }
  function closeSide(){
    document.body.classList.remove('side-open');
    var s=el('sideScrim'); if(s) s.hidden=true;
  }
  if(el('sideOpen')) el('sideOpen').onclick=openSide;
  if(el('sideScrim')) el('sideScrim').onclick=closeSide;
  if(el('sideMini')) el('sideMini').onclick=function(){
    if(window.innerWidth<=900){ closeSide(); return; }
    document.body.classList.toggle('side-mini');
    try{ localStorage.setItem('jy_side_mini',document.body.classList.contains('side-mini')?'1':'0'); }catch(e){}
  };
  try{ if(localStorage.getItem('jy_side_mini')==='1') document.body.classList.add('side-mini'); }catch(e){}
  if(el('convSearch')) el('convSearch').oninput=function(){ JY.render(); };

  document.addEventListener('click',function(e){
    var del=e.target.closest('[data-del]');
    if(del){
      e.stopPropagation();
      var id=del.getAttribute('data-del');
      var t=JY.list().filter(function(x){ return x.id===id; })[0]||{};
      if(window.confirm('删除「'+(t.title||'新对话')+'」？只删本地记录，已存的笔记不受影响。')){
        JY.remove(id);
        document.dispatchEvent(new CustomEvent('jy:removed',{detail:id}));
      }
      return;
    }
    var item=e.target.closest('.conv');
    if(!item) return;
    var tid=item.getAttribute('data-id');
    if(document.body.classList.contains('page-ask')){
      document.dispatchEvent(new CustomEvent('jy:thread',{detail:tid}));
    }else{
      location.href='/ask?t='+encodeURIComponent(tid);
    }
    closeSide();
  });

  if(!document.body.classList.contains('page-ask') && el('newChat')){
    el('newChat').onclick=function(){ location.href='/ask?new=1'; };
  }
  document.addEventListener('keydown',function(e){
    var meta=e.ctrlKey||e.metaKey;
    if(meta&&(e.key==='k'||e.key==='K')){
      e.preventDefault();
      if(el('newChat')) el('newChat').click(); else location.href='/ask?new=1';
      return;
    }
    if(meta&&(e.key==='b'||e.key==='B')){
      e.preventDefault(); document.body.classList.toggle('side-mini'); return;
    }
    if(e.key==='Escape') closeSide();
  });
  JY.render();
})();
"""


SETTINGS_CSS = """
/* ============ 设置弹窗 ============
   参照 DeepSeek：居中弹窗、左边一列分区、右边内容，而不是从右侧滑出的抽屉。
   抽屉会挡住正在看的内容；设置要能被「边看边改」，弹窗更合适。 */
.set-mask{position:fixed;inset:0;background:rgba(17,18,22,.34);z-index:120;}
.set-panel{position:fixed;z-index:121;left:50%;top:50%;transform:translate(-50%,-50%);
  width:min(840px,calc(100vw - 40px));height:min(600px,calc(100vh - 72px));
  display:grid;grid-template-columns:184px minmax(0,1fr);grid-template-rows:auto minmax(0,1fr);
  background:var(--surface);border:1px solid var(--line);border-radius:16px;
  box-shadow:0 40px 80px -44px rgba(0,0,0,.5),0 8px 24px -16px rgba(0,0,0,.18);
  overflow:hidden;animation:setIn .16s ease;}
@keyframes setIn{from{opacity:0}to{opacity:1}}
.set-hd{grid-column:1/-1;display:flex;align-items:center;gap:10px;padding:15px 20px;
  border-bottom:1px solid var(--line);}
.set-hd b{font-size:15px;color:var(--ink);font-weight:600;}
.set-x{margin-left:auto;width:30px;height:30px;border:0;background:transparent;color:var(--faint);
  font-size:20px;line-height:1;cursor:pointer;border-radius:8px;}
.set-x:hover{background:var(--surface-2);color:var(--ink);}
.set-tabs{grid-column:1;grid-row:2;display:flex;flex-direction:column;gap:2px;padding:12px 8px;
  border-right:1px solid var(--line);overflow-y:auto;}
.set-tabs button{border:0;background:transparent;color:var(--muted);font-size:13.5px;padding:9px 12px;
  border-radius:8px;cursor:pointer;white-space:nowrap;text-align:left;}
.set-tabs button:hover{background:var(--surface-2);color:var(--ink);}
.set-tabs button.on{background:var(--hover);color:var(--ink);font-weight:600;}
.set-body{grid-column:2;grid-row:2;overflow-y:auto;padding:18px 22px 26px;}

/* 存储占用：一条堆叠条 + 四项数字。只回答「什么占了空间、还剩多少」 */
.st-usage{display:flex;flex-direction:column;gap:10px;padding:14px;border:1px solid var(--line);
  border-radius:12px;background:var(--surface-2);}
.st-bar{display:flex;height:8px;border-radius:999px;background:var(--line);overflow:hidden;}
.st-bar .seg{height:100%;}
.st-bar .kb{background:#4d6bfe;}
.st-bar .notes{background:#8ea2ff;}
.st-bar .index{background:#c6cff5;}
.st-legend{display:flex;flex-wrap:wrap;gap:10px 16px;font-size:12px;color:var(--muted);}
.st-legend b{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums;}
.st-legend .dot{display:inline-block;width:7px;height:7px;border-radius:2px;margin-right:5px;}
.st-legend .dot.kb{background:#4d6bfe;} .st-legend .dot.notes{background:#8ea2ff;}
.st-legend .dot.index{background:#c6cff5;}
.st-legend .free{margin-left:auto;color:var(--faint);}
.st-note{margin-top:-2px;}
.st-keep{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:12px;color:var(--muted);}
.st-keep select{height:32px;padding:0 8px;border:1px solid var(--line-2);border-radius:8px;
  background:var(--surface);color:var(--text);font-size:12.5px;font-family:inherit;}

/* 接口接入：先给结论（当前能不能用），再给三步操作 */
.api-state{display:flex;align-items:flex-start;gap:10px;padding:12px 13px;border-radius:11px;
  border:1px solid var(--line);background:var(--surface-2);}
.api-state .led{width:8px;height:8px;border-radius:50%;background:#e0a100;margin-top:6px;flex:none;}
.api-state.on .led{background:var(--ok);}
.api-state b{display:block;font-size:13px;color:var(--ink);}
.api-state i{display:block;font-size:12px;color:var(--faint);font-style:normal;line-height:1.6;margin-top:2px;}
.api-steps{margin:0;padding-left:18px;font-size:12px;color:var(--muted);line-height:1.9;}
.api-steps b{color:var(--text);font-weight:600;}
@media (max-width:720px){
  .set-panel{grid-template-columns:1fr;grid-template-rows:auto auto minmax(0,1fr);
    width:100vw;height:88vh;left:0;top:auto;bottom:0;transform:none;border-radius:16px 16px 0 0;
    border-left:0;border-right:0;border-bottom:0;}
  .set-tabs{grid-column:1;grid-row:2;flex-direction:row;overflow-x:auto;border-right:0;
    border-bottom:1px solid var(--line);padding:8px 10px;}
  .set-tabs button{padding:7px 11px;}
  .set-body{grid-column:1;grid-row:3;padding:16px 16px 24px;}
}
.set-pane{display:none;flex-direction:column;gap:12px;}
.set-pane.on{display:flex;}
.set-f{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--muted);font-weight:600;}
.set-f input,.set-f select{padding:9px 11px;border:1px solid var(--line-2);border-radius:var(--r-sm);
  background:var(--surface-2);color:var(--text);font-size:13px;font-family:inherit;width:100%;}
.set-f input:focus,.set-f select:focus{border-color:var(--brand);outline:none;box-shadow:0 0 0 3px var(--brand-soft);}
.set-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.set-note{font-size:12px;color:var(--faint);line-height:1.6;margin:0;}
.set-note.ok{color:var(--ok);}
.set-note.err{color:var(--bad);}
.set-note a{color:var(--brand);text-decoration:underline;text-underline-offset:2px;}
.set-ver-now{font-size:13px;color:var(--text);}
.set-ver-now b{font-family:var(--mono);font-size:12px;color:var(--ink);}
.set-seg{align-self:flex-start;display:inline-flex;border:1px solid var(--line-2);border-radius:10px;padding:2px;background:var(--surface-2);}
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
    '<div class="api-state" id="apiState"><span class="led"></span><div>'
    '<b id="apiStateTitle">未接入模型</b>'
    '<i id="apiStateText">当前使用离线抽取：直接从文档里摘录原句，不调用模型。</i>'
    "</div></div>"
    '<ol class="api-steps">'
    "<li>填<b>接口地址</b>与<b>模型名</b>：兼容 OpenAI 协议的端点都行，地址填到 <code>/v1</code> 这一层。</li>"
    "<li>粘贴<b>密钥</b>：只写进本机 <code>data/app.json</code>，不上传、不回显原文。</li>"
    "<li>点<b>测试连接</b>：等到往返毫秒数出现，说明这一组配置可用。</li>"
    "</ol>"
    '<label class="set-f">接口地址<input id="setBase" autocomplete="off" spellcheck="false"></label>'
    '<label class="set-f">模型<input id="setModel" autocomplete="off" spellcheck="false"></label>'
    '<label class="set-f">密钥<input id="setKey" type="password" placeholder="留空表示保持已保存的密钥" autocomplete="off" spellcheck="false"></label>'
    '<div class="set-row"><button class="btn sm" id="setSave" type="button">保存并启用</button>'
    '<button class="btn ghost sm" id="setTest" type="button">测试连接</button>'
    '<a class="btn ghost sm" href="https://platform.deepseek.com/api_keys" target="_blank" rel="noopener">获取 DeepSeek 密钥</a></div>'
    '<p class="set-note" id="setApiNote"></p>'
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

    # 存储占用与清理：这一块只回答两件事——什么占了空间、点一下能腾出多少
    '<div class="st-usage">'
    '<div class="st-bar" aria-hidden="true">'
    '<span class="seg kb" id="stSegKb"></span>'
    '<span class="seg notes" id="stSegNotes"></span>'
    '<span class="seg index" id="stSegIndex"></span>'
    "</div>"
    '<div class="st-legend">'
    '<span><i class="dot kb"></i>知识库 <b id="stKb">—</b></span>'
    '<span><i class="dot notes"></i>笔记 <b id="stNotes">—</b></span>'
    '<span><i class="dot index"></i>索引缓存 <b id="stIndex">—</b></span>'
    '<span class="free">磁盘剩余 <b id="stFree">—</b> / <span id="stTotal">—</span></span>'
    "</div></div>"
    '<div class="st-keep"><span>保留知识库版本</span>'
    '<select id="stKeep"><option value="0">不清理</option><option value="10">最近 10 版</option>'
    '<option value="30">最近 30 版</option><option value="90">最近 90 版</option></select>'
    '<button class="btn ghost sm" id="stClean" type="button">清理旧版本与索引</button></div>'
    '<p class="set-note st-note" id="stMsg">清理只删旧版本和可重建的索引缓存，'
    "不动当前文档与笔记。</p>"
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
    f'<span class="set-ver-now">记忆文档 <b>v{__version__}</b></span>'
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
  border-top:1px solid var(--line);background:var(--surface);
  min-height:min(70vh,640px);}
.pf-list{border-right:1px solid var(--line);padding:8px;overflow:auto;max-height:78vh;}
.pf-detail{padding:20px 24px;overflow:auto;max-height:78vh;}
@media (max-width:760px){
  .pf-grid{grid-template-columns:1fr;}
  .pf-list{border-right:0;border-bottom:1px solid var(--line);max-height:38vh;}
  .pf-detail{max-height:none;}
}
.files-mask{position:fixed;inset:0;background:rgba(17,18,22,.26);z-index:100;}
.files-panel{
  position:fixed;top:0;right:0;bottom:0;width:min(760px,96vw);z-index:101;display:flex;flex-direction:column;
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
    if(window.__closeSide) window.__closeSide();
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
    // 移动端上侧栏可能正开着：它 z-index 更高，不收起会把弹窗整个挡住
    if(window.__closeSide) window.__closeSide();
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
  // 给别的脚本一个入口：输入框里的「接口」标签点开就要落在对应分区
  window.__openSettings=function(tab){ openPanel(); if(tab) selectTab(tab); };
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
    // 离线不是错误：只在「已接入」时用成功色，未接入保持中性灰
    if($('setApiNote')){
      $('setApiNote').textContent = d.llm.key_ready
        ? ('当前生效：'+(d.llm.effective_model||'')+' @ '+(d.llm.effective_base_url||''))
        : '还没配密钥，问答会走本地抽取，不调用模型';
      $('setApiNote').className = 'set-note' + (d.llm.key_ready ? ' ok' : '');
    }

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
    renderApiState(d.llm||{});
    renderStorage(d.storage||{});
  }

  function sizeText(n){
    n=Number(n)||0;
    if(n<1024) return n+' B';
    var units=['KB','MB','GB','TB'], i=-1, v=n;
    do{ v/=1024; i++; }while(v>=1024&&i<units.length-1);
    return (v>=10?v.toFixed(0):v.toFixed(1))+' '+units[i];
  }
  function renderApiState(llm){
    var box=$('apiState'); if(!box) return;
    llm=llm||{};
    var ready=!!llm.key_ready;
    box.classList.toggle('on',ready);
    if($('apiStateTitle')) $('apiStateTitle').textContent=
      ready?('已接入 '+(llm.effective_model||llm.model||'')):'未接入模型';
    if($('apiStateText')) $('apiStateText').textContent=ready
      ? ('请求发往 '+(llm.effective_base_url||'')+'，密钥已保存在本机。')
      : '当前使用离线抽取：直接从文档里摘录原句，不调用模型。';
  }
  function renderStorage(st){
    st=st||{};
    var kb=(st.kb||{}), notes=(st.notes||{}), idx=(st.index||{});
    var total=(kb.bytes||0)+(notes.bytes||0)+(idx.bytes||0);
    if($('stKb')) $('stKb').textContent=sizeText(kb.bytes)+(kb.versions?(' · '+kb.versions+' 版'):'');
    if($('stNotes')) $('stNotes').textContent=sizeText(notes.bytes)+(notes.files?(' · '+notes.files+' 篇'):'');
    if($('stIndex')) $('stIndex').textContent=sizeText(idx.bytes);
    if($('stFree')) $('stFree').textContent=sizeText((st.disk||{}).free);
    if($('stTotal')) $('stTotal').textContent=sizeText((st.disk||{}).total);
    function pct(v){ return total>0?Math.max(v>0?2:0,Math.round(v/total*100)):0; }
    if($('stSegKb')) $('stSegKb').style.width=pct(kb.bytes||0)+'%';
    if($('stSegNotes')) $('stSegNotes').style.width=pct(notes.bytes||0)+'%';
    if($('stSegIndex')) $('stSegIndex').style.width=pct(idx.bytes||0)+'%';
    if($('stKeep')) $('stKeep').value=String(st.keep_versions==null?30:st.keep_versions);
  }
  if($('stClean')) $('stClean').addEventListener('click',function(){
    var btn=this, label=btn.textContent;
    btn.disabled=true; btn.textContent='清理中…';
    note('stMsg','正在清理，索引会重建一次…','');
    api('POST','/api/settings/storage/clean',{keep:Number($('stKeep').value||0)}).then(function(d){
      if(!d||!d.ok){ note('stMsg',(d&&d.message)||'清理失败',true); return; }
      renderStorage(d.storage||{});
      var freed=sizeText(d.freed_bytes||0);
      var removed=(d.removed||[]).length;
      note('stMsg','已清理 '+(removed?removed+' 个旧版本':'旧版本')+'，释放 '+freed
        +'；当前保留 '+d.keep+' 版。',false);
    }).catch(function(e){
      note('stMsg','清理失败：'+((e&&e.message)||e),true);
    }).finally(function(){ btn.disabled=false; btn.textContent=label; });
  });

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
        f"<title>{title}</title><style>{BASE_CSS}{SETTINGS_CSS}{FILES_CSS}{css}</style></head>"
        f'<body class="page-{active}">'
        '<div class="app">'
        f"{nav(active)}"
        '<div class="main">'
        '<button class="mnav" id="sideOpen" type="button" aria-label="打开侧栏">'
        f"{icon('panel', 17)}</button>"
        f'<div class="stage stage-{active}">{body}</div>'
        "</div></div>"
        f"{FILES_HTML}{SETTINGS_HTML}"
        f'<div id="toasts"></div>'
        # 公共脚本先注入一次：侧栏与设置都要用 esc/toast，页面脚本不再各自复制一份
        f"<script>{JS_UTIL}</script>"
        f"<script>{SIDE_JS}</script>"
        f"<script>{script}</script>"
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
