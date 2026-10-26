"""两个页面（问答 / 知识库）的装配点。

样式、结构、脚本都在 `src/web/` 下：`ask.*` 与 `kb.*`。
本文件只做三件真正需要计算的事：
1. 把 `__MARK__` 占位符换成真正的 logo（HTML 里贴不了 Python 生成的 SVG）；
2. 把 ASCII 图转义成合法 JS 字符串后填进脚本；
3. 调 `shell()` 拼出完整页面。

为什么从 1800 行的字符串改成一个装配文件：内联字符串没法语法高亮、没法 `node --check`，
改一行 JS 要滚动两千行。现在改样式开 .css，改交互开 .js，页面本身读一眼就看完了。
"""
from .theme import BRAND, MARK, shell
from .webassets import load

# ASCII 图是给空状态用的，单独放一个文件免得脚本里夹一段图形
_ASK_ART = load("art.txt")

ASK_CSS = load("ask.css")
ASK_BODY = load("ask.html").replace("__MARK__", MARK)
ASK_SCRIPT = load("ask.js").replace("{{_ASK_ART}}", _ASK_ART.replace("'", "\\'"))
ASK_HTML = shell("ask", "问答 · " + BRAND, ASK_BODY, ASK_SCRIPT, ASK_CSS)

KB_CSS = load("kb.css")
KB_BODY = load("kb.html")
KB_SCRIPT = load("kb.js")
KB_HTML = shell("kb", "知识库 · " + BRAND, KB_BODY, KB_SCRIPT, KB_CSS)
