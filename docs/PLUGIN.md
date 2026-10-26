# 实体控件与插件化说明（v1.17.0）

本文回答三个问题：界面上到底有哪些可点的实体控件、它们能改什么、以及这个项目能不能当成独立插件挂到别的智能体上。
所有结论都来自实测（Playwright 枚举 DOM + 真跑 MCP 进程），不是看代码推测。

## 一、入口

两页（`/ask`、`/kb`）右上角各有一个齿轮：`button#setBtn`，`aria-label="设置"`，尺寸 34×34。
点击打开右侧抽屉。设置按钮上不再挂红点——备份提醒改挂到导航栏的「文件」入口。
抽屉本身：`aside#setPanel` + 遮罩 `#setMask`，`Esc` 或点遮罩关闭，关闭按钮 `#setClose`（×）。

打开后焦点自动落到「接口地址」输入框（实测 `document.activeElement.id === "setBase"`），
键盘用户不需要先 Tab 一圈才能开始配置。

## 二、四个分区的控件清单

统计口径：设置弹窗内 18 个 `<button>`、5 个输入框（含 1 个开关）、1 个 `<select>`、3 个链接；
左侧常驻栏另有「文件」入口按钮 + 红点按钮（`button#filesDot`）、新对话与会话列表项。
`<select>` / `<textarea>` 为 0——所有选择都用分段按钮或系统对话框，没有原生下拉。

### 接口

| 控件 | 元素 | 作用 | 交互与生效 |
|---|---|---|---|
| 接口地址 | `input#setBase` | OpenAI 兼容端点，填到 `/v1` 层 | 需点「保存」；空值或非 http(s) 会被 400 并红字说明 |
| 模型 | `input#setModel` | 模型名 | 同上 |
| 密钥 | `input#setKey`（`type=password`） | API Key | 只回显掩码（`sk-abc******mnop`），留空表示不改；原文不可回读 |
| 保存 | `button#setSave` | 落 `data/app.json` | 点击后同一响应里回显新的「当前生效」，不需要重启 |
| 测试连接 | `button#setTest` | 真发一次 `max_tokens=1` 请求 | 15 秒超时；401 / 403 / 404 / 429 / 连不上分别给不同文案 |

### 存储

| 控件 | 元素 | 作用 | 交互与生效 |
|---|---|---|---|
| 默认位置 / 自定义 | 2 个 `button[data-home]`（分段） | 切换模式 | 选「自定义」才显示目录输入框与「选择…」 |
| 目录 | `input#setHome` | 手填或粘贴绝对路径 | 自动去两端引号（中英文）、去空白、展开 `~` |
| 选择… | `button#setPick` | 弹系统原生目录对话框 | Windows WinForms / macOS osascript / Linux zenity；180 秒超时；**选完自动应用** |
| 应用 | `button#setHomeSave` | 手填路径时提交 | 先试写校验，再重建笔记服务 |
| 打开文件夹 | `button#setOpen` | 拉起资源管理器 / Finder | 只读操作，不改配置 |
| 复制过来 / 不用 | `button#setMigrateGo` / `#setMigrateNo` | 旧位置还有笔记时的迁移提示 | 只复制不移动，同名跳过；不点则保持原样 |

### 对话

| 控件 | 元素 | 作用 | 交互与生效 |
|---|---|---|---|
| 储存对话内容 | `input#setStoreChat` + `label.set-switch` | 是否允许问答页沉淀对话 | 点整行（实测命中区 394×67）即切换并立刻落盘；失败会把开关翻回去并红字提示 |

关闭时的实际范围：问答页不再渲染「存为笔记」按钮，后端拒绝带 `from=chat` 的保存（403）；
智能体经 MCP / API 显式保存不受影响——UI 开关不改协议语义。

### 已存（v1.14.0 起迁出设置，改成导航栏的独立入口）

导航栏「文件」= `button#filesBtn`（图标 + 文字 + 篇数角标），右侧叠一个红点按钮
`button#filesDot`（18×18 点击区，画 7px 圆点）。**点红点只消提醒，不打开抽屉**；
消除状态记在 `localStorage.rag_dot_off`，键是「上次导出时间」，刷新后不会再冒出来。
快捷键 `Ctrl/Cmd + Shift + F` 开合抽屉；不装按钮的客户端可以直接开 `/files`。

| 控件 | 元素 | 作用 | 交互与生效 |
|---|---|---|---|
| 文件入口 | `button#filesBtn`（导航栏右侧） | 打开文件抽屉，看全部已存文件 | 带数量角标；有备份待办时右上角红点 |
| 文件项 | `button.file-item` | 选中后右侧显示标题、时间、标签与各节正文 | 真 `<button>`：可 Tab 聚焦、Enter 激活 |
| 导出全部 | `button#filesExport` | 下载 JSON bundle | 真触发下载；成功后记备份时间、红点消失 |

抽屉本身：`aside#filesPanel` + 遮罩 `#filesMask`，`Esc` 或点遮罩关闭。
打开时先刷一次 `/api/settings`，因此存完新笔记再点进来，角标与备份状态都是最新的。

### 安装

| 控件 | 元素 | 作用 | 交互与生效 |
|---|---|---|---|
| 检查更新 | `button#setUpdate` | 查 GitHub 最新 Release | **只查不装**：4 秒超时、缓存 10 分钟；有新版给三条链接，无新版提示已最新，失败说明原因并给发布页 |
| 下载应用包 | `a#setDownload` | `releases/latest/download/jiyi-app-<版本>.zip` | 普通链接，新窗口打开；取不到地址就退回发布页 |
| 下载插件包 | `a#setDownloadPlugin` | `…/jiyi-plugin-<版本>.zip` | 只含笔记的 MCP 包，同上 |
| 打开文件页 | `a[href="/files"]` | 打开 `/files` | 独立页，可收藏；和抽屉读同一套接口 |
| 复制配置 | `button#setMcpCopy` | 复制 MCP JSON 到剪贴板 | 含当前解释器绝对路径、`PYTHONPATH`、`NOTE_HOME` |
| 写入 Claude Desktop | `button#setMcpInstall` | 写 `claude_desktop_config.json` | 先备份原文件；现有 JSON 坏了不覆盖，直接报错 |

页脚版本号 `button#footVer` 也通到这里：点一下打开设置并切到「安装」分区。

### 没有放进界面的配置

以下仍只能走环境变量，属于有意收口（避免设置面板变成参数垃圾场）：
`RETRIEVAL` / `TOP_K` / `MIN_SCORE`、`RATE_LIMIT_*`、`API_KEYS`、`ADMIN_TOKEN`、
`KB_*`（版本保留数、审批策略）、端口与监听地址。

## 三、能不能当独立插件用

**能，但要说得准确**：它是「MCP stdio 插件 + HTTP 工具接口」，不是浏览器扩展，也不是 pip 包；
而且插件只带**个人笔记**能力，不带文档问答。

### 3.1 实测：脱离项目目录也能跑

在 `C:\Users\...\Temp\mcp-probe2` 目录下，只用 `PYTHONPATH` 指向源码、`NOTE_HOME` 指向临时目录，
启动 `python -m src.notes.mcp_server`，一次会话内完成：

```
initialize   → protocolVersion 2025-06-18，serverInfo agent-notes v1.13.1
tools/list   → save_conversation / search_notes / get_note / update_note
               / note_stats / export_notes / delete_note（7 个）
resources    → notes://schema、notes://index
save_conversation → 生成 notes/2026/10/xxx.md
search_notes → count=1
note_stats   → home / notes / kinds
```

说明它不依赖 cwd、不依赖 Web 服务，也不要求先建目录（首次运行自己建 `notes/ index/ .trash/` 并写 `AGENTS.md`）。

### 3.2 四种集成方式

| 方式 | 适用客户端 | 需要什么 | 能力范围 |
|---|---|---|---|
| **MCP stdio**（推荐） | Claude Desktop、Cursor、Cline、Continue、任何支持 MCP 的桌面智能体 | Python 解释器路径 + 源码目录 + 可写笔记目录 | 7 个笔记工具 + 2 个资源 |
| HTTP + `/tools.json` | 支持 function calling 的自研智能体 | 先起服务（`python -m src.server`），配置 `API_KEYS`（可选） | 同一套 7 个工具；另有 `/api/ask` 问答 |
| 文件直读 | 任何能读本地文件的智能体 | 笔记目录路径 | 只读；`.md` + front matter |
| CLI | 脚本 / 定时任务 | 源码目录 | `save / list / get / rebuild / stats / export` |

MCP 配置示例（设置抽屉「复制配置」生成的就是这段）：

```json
{
  "mcpServers": {
    "agent-notes": {
      "command": "C:\\path\\to\\python.exe",
      "args": ["-m", "src.notes.mcp_server"],
      "env": {
        "PYTHONPATH": "D:\\path\\to\\rag_assistant",
        "NOTE_HOME": "D:\\我的笔记"
      }
    }
  }
}
```

- Claude Desktop 配置文件：Windows `%APPDATA%\Claude\claude_desktop_config.json`；
  macOS `~/Library/Application Support/Claude/claude_desktop_config.json`。
- 其他客户端把同一段 JSON 放进各自的 MCP 配置即可，键名不必是 `agent-notes`。

### 3.3 依赖条件

- **Python 3.11+**（`requirements.txt` 声明；本机实测 3.13）。MCP / HTTP / CLI 全部只用标准库。
- **源码目录**：仓库里没有 `pyproject.toml` / `setup.py`，所以**不能 `pip install`**，
  必须保留目录并用 `PYTHONPATH` 指过去（或把目录放进 `site-packages`）。
- **一个可写目录**：`NOTE_HOME`。不设时默认 `~/agent-notes`。
- **客户端支持 MCP stdio**，或愿意走 HTTP。当前**没有** MCP HTTP/SSE 传输，远程智能体接不了。
- 端口/网络：MCP 方式不需要开端口；HTTP 方式默认只监听本机。
- 可选依赖：`numpy` + `faiss-cpu` 只在「真 embedding」时用，与笔记插件无关。

### 3.4 适用与不适用

**适用**
- 单人、本机使用，想把「和不同智能体的对话」沉淀成可读、可改、可带走的 Markdown。
- Claude Desktop / Cursor / Cline 等已经支持 MCP 的客户端。
- 需要「关掉模型也能用」：规则摘要不联网、不调模型，断网也能整理。

**不适用 / 边界**
- 多人共享、需要权限隔离：没有账号体系，`API_KEYS` 只是单层共享密钥。
- 手机端、纯云端、无法运行 Python 的环境。
- 远程智能体：MCP 只有 stdio，没有 HTTP/SSE 传输。
- 需要文档问答的智能体：那是主服务（`/api/ask` + 知识库），不在这个 MCP 插件里。
- 多客户端同时写同一目录：有跨进程目录锁，能串行写入，但没有做过并发压力验证。

## 四、控件层面的问题（已列入路线图）

1. ~~**「已存」列表项不是按钮**~~（v1.14.0 已修）：改成导航栏入口 + `button.file-item`，
   可 Tab 聚焦、Enter 激活，e2e 覆盖「点开能看到正文」。
2. **没有焦点陷阱**：抽屉打开后 Tab 会跑到背后的页面。个人使用影响小，
   但键盘操作时容易迷失。
3. **接口配置要「保存」，其余即时生效**：这是有意的（避免每敲一个字符就写盘），
   但需要在文案上说清楚，目前只有按钮下方一行小字。

以上都不影响「有实体控件」这个结论：四类真实控件（输入框、按钮、开关、链接）齐全，
写操作有成功/失败反馈，失败会回滚 UI。
