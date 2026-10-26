"""统一设计系统：骨架、导航、图标，以及 `src/web/` 里前端资源的装载点。

两个页面（问答 / 知识库）加一个文件页共用这一份，避免各写一套导致观感割裂。
样式与脚本已经从 Python 字符串搬到 `src/web/`：那边有语法高亮、能跑 `node --check`，
这里只剩下真正需要计算的部分（导航、骨架拼接、版本号替换）。

运行时仍然是零外部依赖、零构建步骤：资源在导入时读进内存，内联拼进 HTML，
不引 CDN、不引字体、不新增静态路由，断网可用。
"""
import os

from .profiles import get_profile
from .version import __version__
from .webassets import load

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
    "plug": '<path d="M9 3v6M15 3v6"/><path d="M6 9h12v2.5A6.5 6.5 0 0 1 11.5 18h1A6.5 6.5 0 0 1 18 11.5V9"/><path d="M12 18v3"/>',
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

# ---------------------------------------------------------------- 前端资源
# 全部在 src/web/ 下：*.css 是样式，*.js 是脚本，*.html 是页面片段。
# 这里只是装载点，改样式改脚本请直接开对应文件，不要往 Python 里塞字符串。
BASE_CSS = load("base.css")          # 设计令牌 + 基础组件 + 侧栏/主区骨架
SIDE_JS = load("side.js")            # 侧栏交互 + 多会话本地存储
SETTINGS_CSS = load("settings.css")  # 设置抽屉（居中弹窗）
SETTINGS_HTML = load("settings.html").replace("{{__version__}}", __version__)
FILES_CSS = load("files.css")        # 文件抽屉（已存内容）
FILES_HTML = load("files.html")
FILES_JS = load("files.js")
# /files：不套抽屉的独立页。给「加不进 WorkBuddy 工具栏」这件事一个可直接收藏、
# 可直接被智能体打开的地址；抽屉那套仍留在两页里，用于不打断问答。
FILES_PAGE_HTML = load("files_page.html")
FILES_PAGE_JS = load("files_page.js")
# 连接智能体：侧栏常驻按钮 + 一份可直接复制的 MCP 配置
AGENT_CSS = load("agent.css")
AGENT_HTML = load("agent.html")
AGENT_JS = load("agent.js")
THEME_HEAD = load("theme_head.html")  # 首屏防闪白：在 <head> 里就把主题定下来
SETTINGS_JS = load("settings.js")
THEME_JS = load("theme.js")
JS_UTIL = load("util.js")            # 页面脚本共用的小工具：转义、toast


def nav(active: str = "", links: bool = True) -> str:
    """左侧常驻栏：会话列表 + 底部三个入口。

    位置参照 DeepSeek：新建对话在最上、历史居中滚动、设置在最下。
    差别只有一处——这里还要挂「文件」抽屉与「智能体」接线口，所以底部是几行而不是一处头像。
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
        # 智能体：应用形式与智能体之间的接线口。点开是状态 + 一份可复制的 MCP 配置，
        # 不是噱头按钮——没有它，用户不知道「智能体也能读这些笔记」。
        '<button class="sb-item" id="agentBtn" type="button" aria-haspopup="dialog" '
        'aria-controls="agentPanel" aria-expanded="false" title="连接智能体 · MCP">'
        + icon("plug", 17) + '<span class="sb-label">智能体</span>'
        '<span class="agent-led" id="agentLed" hidden></span></button>'
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


def shell(active: str, title: str, body: str, script: str = "", css: str = "") -> str:
    """完整页面骨架。css 为页面私有样式，追加在设计系统之后。"""
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{THEME_HEAD}"
        f'<meta name="color-scheme" content="light dark">'
        '<link rel="icon" href="data:,">'
        f"<title>{title}</title><style>{BASE_CSS}{SETTINGS_CSS}{FILES_CSS}{AGENT_CSS}{css}</style></head>"
        f'<body class="page-{active}">'
        '<div class="app">'
        f"{nav(active)}"
        '<div class="main">'
        '<button class="mnav" id="sideOpen" type="button" aria-label="打开侧栏">'
        f"{icon('panel', 17)}</button>"
        f'<div class="stage stage-{active}">{body}</div>'
        "</div></div>"
        f"{FILES_HTML}{AGENT_HTML}{SETTINGS_HTML}"
        f'<div id="toasts"></div>'
        # 公共脚本先注入一次：侧栏与设置都要用 esc/toast，页面脚本不再各自复制一份
        f"<script>{JS_UTIL}</script>"
        f"<script>{SIDE_JS}</script>"
        f"<script>{script}</script>"
        f"<script>{FILES_JS}</script>"
        f"<script>{AGENT_JS}</script>"
        f"<script>{SETTINGS_JS}</script><script>{THEME_JS}</script></body></html>"
    )


# 独立文件页：`/files` 直接用，不必先打开抽屉
FILES_PAGE = shell("files", f"文件 · {BRAND}", FILES_PAGE_HTML, FILES_PAGE_JS)
