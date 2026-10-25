# Changelog

遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与语义化版本。

## [1.14.0] - 2026-10-25

界面改版 + 「已存内容」从设置里独立出来，顺带修掉四处会误导人的行为。

### 新增

- **导航栏「文件」入口**（`#filesBtn`）：位置固定在右上角、主题与设置之间，同尺寸同边框，
  带数量角标与备份提醒红点。点开后是文件抽屉：左列全部已存文件，右侧显示标题、时间、标签
  与各节正文；`Esc` / 点遮罩 / 关闭按钮都能收起，焦点回到入口按钮。
- 抽屉内列表项是真正的 `<button>`：可 Tab 聚焦、Enter 激活（旧实现是 `div` + `onclick`，
  键盘和读屏都够不着）。
- 存完一篇笔记，入口角标与提醒点立刻更新，不用刷新页面。

### 改进

- **视觉换成克制的单色蓝**：`--brand` 从靛蓝紫渐变改为 `#4d6bfe`，去掉 body 的径向渐变、
  图标渐变和卡片投影，主色只出现在主按钮、当前导航项与关键标签上。
- **问答页去卡片化**：整页只剩「对话」和「输入框」两层层级，输入框改成 18px 圆角浮层、
  聚焦时描边变主色；不再用边框把聊天区圈起来。
- **深色模式换中性灰**：原来的深蓝底（`#0b1120`）改成 `#17181c`，与浅色共用同一套令牌。
- 知识库表格重新分配列宽：文件名不再被压成 8 个字，时间列不再截断，操作列三个按钮放得下。
- 页脚压成一行：品牌 · 导航 · 版本号，删掉整段免责声明。

### 修复

- **陈述句里的「提交」被当成待办**：`_TODO` 正则含裸词「提交」，「赎回申请 T 日提交」被判成
  `- [ ]` 待办。改成必须带动作宾语（提交材料 / 申请 / 报告 / 表单 / 审核 / 审批 / 需求 / 名单）。
- **用户提问混进要点与摘要**：助手句子不足 3 条时会补几条用户的，于是「现在安装到…」这种
  祈使句进了要点。去掉补句逻辑，要点只取助手内容；纯用户输入（转存片段）仍走回落分支。
- **`export_notes` 返回的字节数比磁盘实际小**：`write_text` 在 Windows 把 `\n` 转成 `\r\n`，
  差出「行数个字节」。改成 `newline=""` 写入，返回值和文件大小一致。
- **`limit=-5` 静默返回空列表**：现在 400 并说明「不能为负」。
- **`HTTPS://` 大小写被拒**：地址校验是大小写敏感的，粘一个全大写协议头就报「要写成 https://…」。
  现在协议头统一小写化，地址照常可用。
- **笔记预览把 front matter 一起显示了**：弹窗里先看到 `schema: note/v1` 一堆 YAML，
  用户以为存成了乱码。现在只显示正文（摘要 / 要点 / 决策…）。
- 设置抽屉去掉「已存」分区（内容迁到文件抽屉），分区从 5 个减到 4 个。

### 测试

- `test_notes_digest_rule` 29 → 30 项：新增「陈述句不进待办、提问不进要点」。
- `test_settings` 61 → 71 项：新增文件入口、文件抽屉挂在 `body` 下、已存不再出现在设置里、
  大写协议头规范化。
- `e2e_settings` 45 → 48 项：文件抽屉开合、列表项点开读正文、导出触发下载、导出后红点消失。
- 另同步更新 README 的四张截图（旧图是改版前的深蓝紫界面）。

## [1.13.2] - 2026-10-25

把项目装进 WorkBuddy 实测时暴露的一个字段契约不一致，顺手修掉。

### 修复

- **显式标题被压成 24 字**：`hint.title` 由调用方给出时也走 `_short(raw, 24)`，
  而网页标题输入框写的是 `maxlength=120`、`PATCH` 也放行 120 字。
  同一个字段「创建时 24、修改时 120」，用户刚打的标题点保存就多出一个省略号。
  现在显式标题按 120 保留，只有自动取名（取首条用户消息）才压到 24 字。

### 测试

- `test_notes_digest_rule` 29 项：断言按「显式 / 自动」分叉，另加一条
  「显式标题原样保留」用例（28 字标题必须一字不改）。


## [1.13.1] - 2026-10-25

第二轮审查的修复版：全部是「数据安全」与「语义自相矛盾」类问题，没有新功能。

### 修复

- **配置写坏后保存会吞掉密钥**：手改 `data/app.json` 少个逗号时，界面显示的是默认值，
  再点一次保存就把原文件整段覆盖了。现在覆盖前先检测原文件是否合法，不合法先备份成
  `app.json.bak-<时间>`；设置抽屉顶部红字说明「配置文件无法解析」或「已备份到 …」。
- **保存后同一响应里的「当前生效」还是旧值**：`config` 的 1 秒缓存只认 TTL，
  保存后同秒内读到的仍是旧模型。改为按写入版本号精确失效。
- **`"store_chat": "false"` 被当成开启**：`bool("false")` 为真。新增严格布尔解析，
  读路径无法识别按关闭处理，写路径直接 400。
- **手写无时区时间戳会让设置面板 500**：`last_export_at` 少了时区时与 UTC 相减抛
  `TypeError`。现在按本机时区补齐。
- **记事本存成 ANSI/GBK 会让服务起不来**：配置文件按 UTF-8 解码失败直接抛
  `UnicodeDecodeError`（不在原来的 `OSError` 分支里）。现在按 UTF-8 → GBK 依次解码，
  都不行才按坏文件处理；保存统一写回 UTF-8。
- **HEAD `/api/notes/export` 被记成一次备份**：探测一下红点就消失。只有真正的 GET 下载
  且状态 200 才记。
- **「存为笔记」要打开一次设置才出现**：开关状态只在设置抽屉打开时写入页面，
  干净页面里按钮永远不渲染。页面加载时即同步；服务端 `view()` 统一走 `store_chat()`，
  `STORE_CHAT` 环境变量从「文档里有、实际不生效」变为真生效。
- **配置为空时表单点保存必然 400**：接口地址/模型输入框改为回填当前生效值，坏配置可在界面里改回来。
- **创建笔记不校验 `status`**：PATCH 拦得住的值能从 POST 放进来。创建与修改现在用同一套枚举。
- **笔记查重与写入不在同一把锁里**：网页与 MCP 同时保存同一段对话会产生两篇。查重挪进锁内。
- **`_check_home` 的写权限探针可能删掉同名文件**：固定 `.write-test` 改为 `mkstemp` 唯一名。
- **导出记时间与保存设置可能互相覆盖**：两处整文件读改写加进程内锁。

### 测试

- `test_settings` 42 → 61 项：坏配置备份与提示、GBK/未知编码、无时区时间戳、字符串布尔、
  `STORE_CHAT` 兜底、保存即生效、探针不误删文件。
- `e2e_settings` 45 项：坏配置提示链路（写入坏 JSON → 页面提示 → 保存 → 告知备份路径）、
  HEAD 不算备份。
- `e2e_notes`：`APP_CONFIG` 与 `STORE_CHAT` 固定到临时环境，不再依赖开发机的
  `data/app.json`（此前在干净环境/CI 会超时）。
- `test_notes_api`：新增「创建时状态枚举」用例。

### 文档

- 新增 `docs/PLUGIN.md`：设置抽屉内 19 个按钮 / 4 个输入框 / 1 个开关的逐项说明与交互方式，
  MCP 插件脱离项目目录的实测结果、四种集成方式、依赖与适用场景。
- 新增 `docs/ROADMAP.md`：P0–P3 改进排序（含工作量与「不建议做」清单）。

## [1.13.0] - 2026-10-25

界面收口到「默认只看该看的」：能配的东西全进一个抽屉，次要内容默认收起。

### 新增

- **设置抽屉**（`src/appconfig.py` + `theme.SETTINGS_*`）：两端页面右上角一个入口，五个分区
  接口 / 存储 / 对话 / 已存 / 安装。默认隐藏，点开才出现。
- **项目内接入 API**：地址、模型、密钥直接在页面填，落 `data/app.json`，保存即生效
  （生成层每次调用都重读配置，不用重启）；「测试连接」真打一次请求，
  401 / 404 / 429 / 超时分别给可读原因。
- **存储位置可选**：默认位置或任意绝对路径。目录可以用系统原生选择框挑
  （Windows 走 PowerShell + WinForms，macOS 走 osascript，Linux 走 zenity / kdialog），
  也可以手填或从资源管理器粘贴（自动去掉两端的引号）。应用前先试写校验，切换后重建笔记服务；
  切换时若旧位置还有笔记，会提示「复制过来」——同名文件一律跳过，不覆盖手改过的内容。
  「打开文件夹」直接拉起文件管理器。CLI 与 MCP 读同一份配置，换位置不用改环境变量。
  无图形环境或选择框不可用时返回可读提示，回退到手填，不会静默失败。
- **「储存对话内容」开关**：默认关。关闭时回答下方不出现「存为笔记」，接口层也拒绝写入（403）；
  打开后按钮出现在每条回答下方。
- **已存内容面板**：设置里直接看最近 30 条，点开读全文，不用跳知识库页。
- **备份提醒**：面板里显示「上次备份 N 天前 / 还没备份过」，导出后立刻变「今天备份过」；
  超过 30 天或从未导出、且库里确实有笔记时，齿轮图标带一个红点。
  判断依据是真导出过（`notes.last_export_at`），不去猜用户有没有手动拷走目录——
  猜错会让人以为有保障。
- **插件安装**：生成 MCP 配置（当前解释器绝对路径 + `PYTHONPATH` + `NOTE_HOME`），
  可复制给任意 MCP 客户端，或一键写入 Claude Desktop（先备份原文件；坏 JSON 不覆盖）；
  「下载到电脑」指向 Releases 最新包。

### 变更

- 配置优先级改为「显式参数 > 界面配置 > 环境变量 > 代码默认」，
  界面里清空的项不再被环境变量顶回来。
- 页脚精简为一行；知识库页「说明」卡改为折叠。
- 版本升到 1.13.0。

### 安全

- 设置里含模型密钥，`data/app.json` 已加入 `.gitignore`；接口只回掩码，不回原文。
- 修改类接口仅本机可调，非本机需 `ADMIN_TOKEN`。

### 测试

- `tests/test_settings.py`：配置读写、掩码、非法地址与路径拒绝、坏文件降级、
  优先级、路径清洗（引号 / 空白 / 中文引号）、笔记库采用新位置、面板挂载位置。
- `tests/e2e_settings.mjs`：抽屉开合、五个分区、保存与回读、原生选择不可用时的降级、
  切换存储与笔记迁移、开关语义（拦对话、不拦智能体）、展开正文、MCP 生成、无脚本报错。

## [1.12.0] - 2026-10-24

笔记从「能用」补成「能交给任何智能体用」：MCP 通道、模型摘要、页面编辑、离线导出。

### 新增

- **MCP stdio 服务**（`src/notes/mcp_server.py`，`python -m src.notes.mcp_server`）：JSON-RPC 2.0 逐行传输，
  7 个工具（保存 / 搜索 / 读取 / 修改 / 删除 / 统计 / 导出）+ 2 个资源（`notes://schema`、`notes://index`）；
  协议版本回显与回落、未知方法 `-32601`、坏 JSON `-32700` 均不中断会话；stdout 只跑协议，日志走 stderr。
- **大模型摘要**（`src/notes/digest_llm.py`）：`--digest auto|llm`；严格 JSON 校验（剥代码围栏、校验 `摘要` 非空、
  丢弃非标准小节、`kind` 非法回落 `qa`）；超时 / 限流 / 坏 JSON / 无 Key 一律回落规则摘要，
  并在 front matter 记 `digest_fallback`；`llm` 模式失败给可读错误而不是静默降级。
- **知识库页「笔记」分区**：文档 / 笔记两个分区切换；笔记可搜索、按类型与状态筛选、查看全文、
  改标题标签小节、加减小节、删除（进 `.trash`）、导出 HTML / JSON；保存带 `rev`，冲突自动重载。
- **问答页「存为笔记」**：每条回答下方入口，先 `commit=false` 预览再落盘，可改标题/标签/类型；
  重复内容提示「已经存过了」。
- **离线导出**（`src/notes/export.py` + `GET /api/notes/export` + `python -m src.notes export`）：
  自包含单文件 HTML（内联 CSS/JS、无外链、深色跟随系统、打印隐藏工具栏、正文转义防注入）与 JSON bundle；
  临时文件 + 原子替换，失败不毁旧文件。
- **`AGENTS.md`**：仓库根目录的接入说明；`NOTE_HOME` 首次初始化还会写一份同名说明，用户改过就不再覆盖。
- **测试**：`test_notes_mcp`（31 项）、`test_notes_digest_llm`（25 项）、`test_notes_export`（26 项）、
  `tests/e2e_notes.mjs`（23 项，自启服务）；`test_server` 增加面板结构断言（用 HTMLParser 检查父子关系）。
- **发布脚本**（`tools/publish_release.py`）：一条命令建 GitHub Release 并上传 zip，正文直接摘 CHANGELOG；
  重复执行只同步正文、跳过已存在附件，发布后把最高版本标回 latest。凭据复用 git 已存的那份，不额外配令牌。

### 变更

- `GET /tools.json` 工具声明 5 → 7（新增 `note_stats`、`export_notes`），与 MCP 共用同一份 schema。
- `/api/notes/export` 返回内容本身而不写服务器磁盘：浏览器拿到就能下载，服务端不留文件。
- `apiHeaders` / `ragApiKey` 上移到公共脚本层，知识库页也能带 `X-API-Key`。
- 版本升到 1.12.0。

### 修复

- 知识库页两个分区最初因为少一个闭合 `</div>`，笔记面板被浏览器自动嵌进文档面板，
  表现为「切过去空白」。已修正，并用 HTMLParser 断言两个面板同级，避免同类问题再靠肉眼发现。
- 「存为笔记」的点击绑定一度落在未命中反馈里（`bindFeedback` / `bindMissFeedback` 两处相似代码），
  已移到正确分支并补 E2E。

## [1.11.0] - 2026-10-24

笔记接上 HTTP：从「只有命令行能用」变成「任何智能体都能调」。

### 新增

- **六个端点**：`POST /api/notes`（保存/预览）、`GET /api/notes`（筛选）、`GET /api/notes/{id}`（含 `rev`）、`PATCH /api/notes/{id}`（乐观锁）、`DELETE /api/notes/{id}?confirm=1`（软删除）、`GET /api/notes/stats`。
- **乐观锁**：`PATCH` 必须带 `rev`（文件内容指纹），不一致返回 409 + 当前 `rev`；避免「人刚改完、智能体又按旧内容覆盖」。`force=true` 可显式跳过。
- **删除确认**：`DELETE` 不带 `confirm=true` 返回 400 `confirm_required`，文件不动；确认后只移入 `.trash`。
- **`GET /tools.json`**：5 个 OpenAI function calling 工具声明（保存/搜索/读取/修改/删除），带 `base_url` 与端点映射。
- **OpenAPI 扩展**：`/openapi.json` 从 18 个路径增到 21 个，新增「笔记」标签与三个 path 条目。
- **鉴权**：配了 `API_KEYS` 时，`/api/notes*` 与问答接口同口径（Bearer / X-API-Key），401 带 `WWW-Authenticate`。
- **CORS（默认关）**：`NOTES_CORS=*` 或来源白名单才放行，支持 `OPTIONS` 预检；个人笔记不默认对浏览器开放。
- **测试**：`test_notes_api`（11 组：CRUD / 去重 / 预览 / 筛选 / 乐观锁 / 小节编辑 / 非法输入 / 删除确认 / 统计 / 预检 / 契约 / 鉴权）。

### 变更

- 请求体上限：问答接口仍是 8 KB，笔记接口单独放宽到 2 MB（一段对话可能很长）。
- `src/notes/api.py` 作为协议层，`src/notes/contract.py` 放 OpenAPI 片段；MCP 接入时复用同一份参数与错误码。
- 版本升到 1.11.0。

## [1.10.0] - 2026-10-24

页面收口到两页，并落地「智能体笔记」第一步：不接大模型也能把对话整理成可读、可改、可流通的 Markdown。

### 新增

- **`src/notes/`（零依赖）**：`model`（Note 与 Markdown 往返）、`store`（目录/原子写/目录锁/索引自愈）、`index`（notes.jsonl 派生缓存）、`select`（切片与指纹）、`digest_rule`（规则摘要）、`service`（统一用例层）、`cli`（命令行）。
- **存储契约 Note v1**：`NOTE_HOME`（默认 `~/agent-notes`）下 `notes/YYYY/MM/<id>.md`，front matter 固定 `schema/id/title/created/updated/kind/status/tags/source/digest/hash`，正文六段（摘要/要点/决策/待办/原文/引用），未知小节与未知字段原样保留；文件名用 id，避免改名与跨平台编码问题。
- **CLI**：`save / list / get / rebuild / stats`；`--draft` 只预览不落盘，`--select-indices | --select-range | --select-keyword` 决定存哪几段，`--keep-raw` 保留原文，`--json` 给机器读。
- **容错**：front matter 缺失或写坏 → `external: true` 降级仍可读；索引被删 → 读路径自动扫盘重建；外部新增的 `.md` 直接纳入。
- **去重**：按选中内容生成 `hash`，同内容再次保存返回 `duplicate_of`，不产生第二个文件；若这次显式要求保留原文而旧笔记没有，会补写进同一篇。
- **测试**：`test_notes_store`（14 组：路径/读回/手改自愈/索引重建/去重/外部文件/坏格式/选择/原文/软删除/锁/错误/统计/CLI）、`test_notes_digest_rule`（28 项：正常 12 / 边界 5 / 对抗 3 / 非法输入 8）。

### 变更

- **页面从四页收成两页**：删除首页与数据中心（`src/insights.py` 与 `web_pages.py` 中首页/看板模板，约 600 行）；导航与页脚只剩「问答」「知识库」。
- `/`、`/index.html`、`/insights`、`/dashboard`、`/report` 一律 302 到 `/ask`，旧链接不会 404。
- 移除 `/api/report/export`（汇报页不再作为服务页面）；`python -m src.report --out x.html` 仍可导出独立文件。
- 版本升到 1.10.0。

### 决策记录

- 存储默认 `~/agent-notes`（跨项目、跨智能体复用），`NOTE_HOME` 或 `--home` 覆盖。
- 原文默认不保存，`--keep-raw` 或 `NOTE_KEEP_RAW=on` 才写「原文」段。
- 笔记浏览入口下一步并入 `/kb` 的第二分区，不新增第三个页面。
- 接入顺序：先 HTTP（便于自测与 CI），再做 MCP；MCP 只做 stdio。

### 性能（本机 1000 篇）

- 保存 P50 12.0 ms / P95 19.0 ms；列出 1000 篇 20.9 ms；索引全量重建 2.0 s（4 线程并行读；单线程 14.7 s）；单篇约 600 B。

## [1.9.0] - 2026-10-24

页面结构重整：看板与汇报合并为「数据中心」，用可收起的侧栏切换模块；问答页与知识库页保持不变。

### 新增

- **数据中心 `/insights`**：原评测看板与汇报页合并为一页，侧栏六项（概览 / 质量 / 用例 / 反馈 / 日志 / 汇报）切换面板，一次只显示一个模块，不再需要跨页跳转。合并后单页 61 KB（原两页合计约 74 KB）。
- **可收起侧栏**：桌面端展开 210px，收起后宽度归零、主内容从 886px 拿满到 1116px；状态存 `localStorage` 并在首屏前置恢复，刷新不跳变。窄屏改为纵向折叠，收起后高度为 0（实测 `sideH=0`），不占任何纵向空间；手机端选完模块自动收起。
- **无障碍与动效**：切换按钮带 `aria-controls` / `aria-expanded` 与随状态变化的 `aria-label`；宽度过渡 240ms，`prefers-reduced-motion` 时取消。

### 变更

- 导航从五项收敛为四项（首页 / 问答 / 知识库 / 数据中心），页脚同步。
- `/dashboard` 与 `/report` 改为 302 到 `/insights#p-overview` / `/insights#p-report`，旧链接与收藏夹不断。
- 模块内文案精简：KPI 副标、面板提示、出题说明由整句改为短语，去掉重复的解释性长段落。
- 独立汇报导出（`/api/report/export`、`python -m src.report`）保持原样，仍是不带侧栏的单文件 HTML。
- 版本升到 1.9.0。

### 测试

- `test_server` 改为校验 `/insights` 的三个关键片段，并新增旧入口 302 断言。
- `e2e_pages.mjs` 改为四页 + 侧栏专项：展开占位、收起归零、主内容变宽、`aria-expanded`、刷新保持、窄屏高度归零，共 15 项新断言。

## [1.8.0] - 2026-10-22

P2 五项：后台/增量重建索引、汇报页缓存与版本硬链接、深色模式 / 减动效 / 图标统一、API Key + OpenAPI、Playwright 五页 E2E。

### 新增

- **后台重建索引**：`KB_ASYNC_RELOAD=on`（默认）时，上传 / 删除 / 审批后接口立即返回（实测约 100 ms），索引在后台线程构建，构建期间继续用旧索引服务；`GET /api/health` 新增 `index`（`rebuilding` / `pending` / `builds` / `last_ms` / `last_error` / `parsed_docs` / `reused_docs`），知识库页轮询后自动刷新。连续上传只置 `pending`，由同一线程再跑一轮，不并发重建。
- **增量解析**：`load_corpus` 按文件 `mtime+size` 缓存分块结果，只重读变更文件；配合版本硬链接保留 mtime，修改一份文档时实测「解析 1 / 复用 3」。
- **版本硬链接与保留策略**：新版本对未变更文件用 `os.link`（不支持硬链接的文件系统自动回退复制），版本写入从 O(全量) 降为 O(变更)；`KB_KEEP_VERSIONS`（默认 30，0=不清理）保留最近 N 版，活动版本与待审批基线版本永不删除。版本 manifest 记录 `linked_docs`。
- **汇报页缓存**：`report.collect()` 以知识库文件 + 评测报告 `mtime/size` + 检索配置为签名，命中直接复用；trace 指标用 `REPORT_CACHE_TTL`（默认 60s）容忍延迟，避免每问一次就失效。实测 `collect` 32.9 ms → 0.87 ms，`/report` 整页 53 ms → 16 ms。
- **深色模式**：`data-theme` + 设计令牌，导航右侧一键切换并记忆（`localStorage`），首屏前置脚本避免闪烁；覆盖五个页面与独立汇报页。`prefers-reduced-motion: reduce` 时关闭过渡、动画与平滑滚动。
- **图标统一**：反馈按钮的 👍/👎 换成与全站一致的 1.7 描边 SVG；新增太阳/月亮图标。
- **API Key**：`API_KEYS=web:sk_xxx,ci:sk_yyy`（也接受不命名），支持 `Authorization: Bearer` 与 `X-API-Key`，常量时间比较；未配置时保持开放。401 带 `WWW-Authenticate`，限流与成本按 Key 统计（`rag_api_tokens_total` / `rag_api_cost_usd_total`），审计只记名字不记密钥。问答页在启用后出现 Key 输入条，存 `sessionStorage`。
- **OpenAPI**：`GET /openapi.json`，18 个路径、请求/响应 schema、鉴权方案与检索配置（`x-retrieval` / `x-model`）。
- **Playwright 五页 E2E**：`tests/e2e_pages.mjs` 自启服务，检查五页 HTTP 200、关键选择器、标题、5 项导航、1280/390px 无横向溢出、无控制台错误，以及深色模式持久化、减动效；无浏览器时明确跳过。CI 增加独立 e2e job。
- **测试**：`test_async_reload`（立即返回 / 重建中可问答 / 增量复用 / 重复触发合并）、`test_report_cache`（命中 / 报告失效 / 知识库失效 / TTL=0）、`test_kb_hardlink`（inode 复用 / 保留 N 版 / 回退复制）、`test_auth_openapi`（401 / 两种携带方式 / 契约）。

### 变更

- 上传、删除、审批、回滚的响应新增 `rebuilding` 与 `index`；重建中 `chunks` 返回 `null`，不再回旧值误导。
- 知识库列表以版本库活动目录为准，重建期间新文件不会短暂“消失”。
- `/api/health` 增加 `auth`（只回模式与 Key 数量，不回名字）。
- 版本升到 1.8.0。

### 修复

- `reload_async` 在「已有重建进行中」分支内重复获取非重入锁会自锁；改用 `RLock`，并由 `test_async_reload` 的连续触发用例守住。

## [1.7.0] - 2026-10-22

P1 七项：传输优化、日志轮转尾读、判域前置、对比度与字号、未命中反馈与答案元信息、会话历史与导出、表格入库。

### 新增

- **HTTP 传输层**：`Handler.protocol_version = "HTTP/1.1"` + 定长响应，连接可复用；`_send` 统一做 gzip（`/ask` 51 KB → 15.5 KB）、弱 ETag 协商与 `304`；JSON 接口 `Cache-Control: no-store`；补 `do_HEAD`（原为 501）。
- **日志轮转与尾读**：新增 `src/jsonl.py`，`append_line` 按 `LOG_MAX_BYTES`（默认 16 MB）/ `LOG_KEEP` 轮转；`tail_lines` 从文件尾按 64 KB 反向读取。`audit.tail`、`metrics.summarize`、`/api/trace`、`/api/audit` 全部改用。37 MB trace 实测 11 ms（全量读 86 ms）。
- **未命中反馈**：`no_answer` 卡片收「应该怎么答 + 哪份文档有答案」，`/api/feedback` 新增 `behavior` / `query` / `expected` / `document` / `session_id` / `kb_version` 字段并返回 `need`。
- **答案元信息**：脚注显示知识库版本、引用条数、引用覆盖率、检索分；未命中显示「最高分 / 阈值」（`min_score` 随响应返回）。
- **会话历史与导出**：`localStorage` 保留最近 40 轮，刷新恢复最近 12 轮；新增「导出 Markdown」（问题 / 答案 / 引用 / 元信息）；清空对话同步清理本地记录。
- **表格入库**：新增 `src/table_text.py`，标准库解析 `.xlsx`（zip + sharedStrings + worksheet）与 `.csv` / `.tsv`（UTF-8 → GB18030 兜底，分隔符自动嗅探），每个工作表转 Markdown 表格；上传、版本库、关键词抽取全链路打通。
- **测试**：`test_http_transport`（保活 / gzip / 304 / HEAD / SSE）、`test_jsonl_log`（跨块尾读 / 截断行 / 轮转 / 大文件延迟）、`test_table_ingest`（xlsx 夹具 / 编码 / 竖线转义 / 切分 / 关键词）、`test_retrieval_order`（域外 0 次扩展 / 扩展更差不替换 / 扩展异常降级）；CI 增加四步。

### 变更

- **判域前置、扩展后置**：先用原问题检索并过置信度闸门，通过后才做查询扩展；扩展结果只在分数更高时替换原结果。域外问题少 1 次 LLM + 1 次 embedding；扩展失败降级为原问题检索（`expansion_error` 写 trace），不再 500。
- **对比度与字号**：`--muted` 改为 `#4a5468`（7.61:1）、`--faint` 改为 `#667085`（白底 4.97:1 / 浅底 4.65:1，原为 2.58:1 / 2.41:1）；`theme.py` 与 `web_pages.py` 中 69 处小于 12px 的字号统一抬到 12px；移动端输入框 16px，避免 iOS 聚焦缩放。
- **表格行按整行入库**：Markdown 表格不再按管道符切成清单，条目片段改为 `表头：值 · 表头：值`，
  直出答案不会再把 `| 产品 | 1000 元 |` 原样吐给用户；表头单元格指向第一行数据（问「起购金额」给一条真实记录）。
- **扫描件提示**：`pdf_ingest.assess` 的告警改为可操作步骤（先 OCR、另存为 docx/txt 再上传），失败响应带 `need_ocr`。
- 上传支持 `.xlsx` / `.csv` / `.tsv`；知识库页与上传提示同步。
- 版本升到 1.7.0。

## [1.6.0] - 2026-10-21

P0 五项落地：流式输出、多轮会话、引用原文、审批界面、知识库接口预计算；未命中不再转人工。

### 新增

- **流式问答**：`POST /api/ask/stream` 以 SSE 返回 `delta` / `replace` / `final`；生成层解析上游 `stream:true`，检测 `[DONE]` 缺失（连接被掐断）并整体降级为抽取式；前端边收边渲染，发送按钮在生成中变为「停止」，`AbortController` 可中断。
- **多轮会话**：`src/sessions.py` 保存最近 3 轮（30 分钟 TTL、最多 1000 会话）；`session_id` 随请求上报，追问（「那 R2 呢」）会拼上上一轮问题，独立问题不拼；`POST /api/session/clear` 清理。
- **引用原文**：citation 增加 `doc_id` / `chunk_index` / `version` / `snippet`；新增 `GET /api/source?doc=&chunk=`，问答页点击 `[1]` 打开右侧原文抽屉并高亮命中行。
- **审批界面**：知识库页展示待审批变更、文件动作与风险提示；`GET /api/kb/change?id=` 返回统一 diff，可直接通过/驳回；每份文档新增「历史」入口与文档级回滚；配置 `ADMIN_TOKEN` 时可在面板内填写令牌（存 sessionStorage）。
- **知识库关键词预计算**：`KeywordIndex._build_doc_terms()` 在建索引时按文档缓存关键词；`/api/knowledge` 与 `/api/keywords` 不再逐文档全量扫描（500 文档/2.5 万条目实测 506 ms → 0.26 ms，构建一次 10 ms）。
- **测试**：`test_session`（上下文改写/TTL/轮数）、`test_stream`（SSE 事件顺序/多轮/未命中）、`test_generator_stream`（真实 SSE 解析/用量/截断替换）；CI 增加三步。

### 变更

- **未命中不再转人工**：`no_answer` 统一返回「无法找到答案。」；删除 `/api/handoff`、工单表单、`logs/handoff.jsonl` 与页面转人工入口；相似问题保留。
- `/api/ask` 响应增加 `session_id` / `context_query` / `turn` / `kb_version`；审计记录 `session_id` 与 `stream`。
- 知识库页每行新增「历史」按钮；问答页引用由纯文本改为可点击按钮。
- 版本升到 1.6.0。

## [1.5.0] - 2026-10-21

关键词直出精度治理：命中之后加否定/极性、解释型意图、单文档收敛四道闸门，匹配改为倒排索引。

### 修复

- **否定越界**：「我不爱吃香菜」同时返回「不吃的食物」与「爱吃的食物」，答案自相矛盾。现在命中位置前 3 字内的否定词会让正向条目本次失效，并记 `negated`。
- **极性冲突**：「我不喜欢的运动是什么」会把「运动：每周三次游泳」当成答案。现在同族条目（去掉极性后的核心词相同）按问句极性取舍，中性/反向条目记 `polarity_conflict`。
- **度量碎片入库**：「每次 1 小时」被当成条目。现在 `每次/每天 + 数字` 这类度量短语不进索引；同时修正「过滤后只剩一项导致整行降级为单值标签、真条目一起丢失」的连带问题。
- **引用编号错位**：多处命中同一原文时，`citations` 里有多余条目而正文没有对应 `[n]`。现在先去重再编号，直出答案内联 `[n]`。

### 新增

- **四道闸门**：`KEYWORD_GUARD=on`（默认）启用否定作用域、极性冲突、解释型意图（为什么/怎么/区别/流程）与单文档收敛；`off` 回到 1.4.0 行为，便于 A/B。`KEYWORD_MULTI_DOC=on` 可放开跨文档直出。
- **核心词别名**：「喜欢的音乐」补「音乐」、「讨厌的天气」补「天气」，只在第一人称提问时生效，避免「明天天气」被截胡。
- **可观测**：响应新增 `keyword_gate`、`keyword_rejected`、`keyword_polarity`；指标新增 `rag_keyword_rejected_total{reason}`、`rag_keyword_gate_total{gate}`；审计日志记录闸门与被挡词。
- **倒排索引**：匹配从「遍历全部条目 × 别名」改为「枚举问句子串查字典」。`tests/bench_keyword.py` 实测 6750 条目下单次 0.018 ms（线性扫描 14.25 ms，约 800×），2 万条目约 2800×；结果与线性实现一致（`test_keyword_precision` 有对照）。
- **测试与评测**：`tests/test_keyword_precision.py` 覆盖否定、极性、意图、度量噪声、单文档、开关回退、索引一致性、引用对齐；`tests/eval_keyword.py` 以 13 条应直出 + 9 条不应直出标注集输出指标（当前 13/13 命中、0 误伤）。CI 增加这两步。

### 变更

- `/api/keywords` 与 `/api/health.keywords` 增加 `guard`、`multi_doc`、`by_polarity`。
- `tools/keyword_demo.py` 默认问题加入否定与解释型用例，逐条打印闸门与被挡原因。
- README 4.9 节补充四道闸门、配置项与边界；版本升到 1.5.0。

## [1.4.0] - 2026-10-21

新增「关键词直出」路径：清单/标签类条目命中时本地返回，不调用任何模型；页面进一步精简。

### 新增

- **关键词索引**：`src/keywords.py` 从清单项、表格行、`标签：值`、`## 关键词` 段抽条目，附带原文片段、出处与权重；章节名仅用于展示，不触发直出。
- **本地直出**：`pipeline.ask` 在检索前先做关键词匹配，命中即返回原文片段 + 引用，结果标 `path=keyword`、`mode=keyword_local`、`api_called=false`，不经过查询扩展 / embedding / 生成 / 补引用。
- **API 整理（可选）**：`KEYWORD_LLM=auto` 且配置 Key 时，每份新增/变更文档调用一次模型生成摘要与同义说法；`term` 必须在原文出现，snippet 一律从原文截取，解析失败保留本地结果。
- **接口**：`GET /api/keywords`、`GET /api/keywords?name=`、`POST /api/keywords/rebuild`；`/api/knowledge` 返回每份文档的关键词与数量，`/api/health` 返回关键词索引状态。
- **指标**：`rag_keyword_hit_total`、`rag_answer_path_total{path}`、`rag_local_answer_total`；响应头 `X-Answer-Path`，审计字段 `path` 与 `api_called`。
- **演示与测试**：`data/demo/小a的生活习惯.md`、`tools/keyword_demo.py`、`tests/test_keywords.py`（含假端点请求数断言）、`tests/test_keyword_api.py`。

### 变更

- 知识库页新增「关键词」列，点击展开词表与摘要；说明文案同步直出规则。
- 问答页命中时显示「本地直出」标签、命中词与「未调用模型」状态，不展示通道/模型。
- 首页右侧示意卡改为两条回答路径（关键词本地直出 / 检索生成），移除原浏览器窗口示意；知识库说明精简为 4 条。
- 版本升到 1.4.0；README 新增 4.9 节，架构文档与 CI 同步。

## [1.3.0] - 2026-10-20

检索升级为真 embedding、多实例状态外置、知识库版本化与审批。

### 新增

- **真 embedding 检索**：`src/embeddings.py` 接入 OpenAI 兼容 `/embeddings`（bge 同协议），批请求、429/5xx 退避重试、墙钟上限、维度探测与内容缓存；`RETRIEVAL=embedding` 启用。
- **向量索引**：`src/vector_store.py` 提供纯 Python / NumPy / FAISS（flat、ivf）三种后端，manifest 记录模型、维度、语料指纹与后端；指纹不匹配自动重建。
- **索引工具**：`tools/build_index.py` 支持全量重建、后端选择与构建后抽查。
- **多实例状态**：`src/redis_client.py`（零依赖 RESP2）+ `guards` 的 Redis 限流（Lua 令牌桶）、幂等（SET NX PX）、日 token 预算（INCRBY）；Redis 故障回退本地并暴露健康状态。
- **集中观测**：`GET /metrics` 输出 Prometheus 指标（请求、延迟直方图、限流、幂等重放、降级、token、版本）；`LOG_SINK=stdout|both` 输出结构化审计 JSON；新增 `deploy/prometheus.yml`、`deploy/fluent-bit.conf` 与多实例说明。
- **知识库版本库**：`src/kbstore.py` 管理 `data/kb/versions/vNNNN`、`pending` 变更、`state.json` 活动指针；上传先暂存，审批后生成新版本。
- **审批与文档级回滚**：`GET /api/kb/versions`、`/api/kb/changes`、`/api/kb/doc_history`，`POST /api/kb/approve|reject|rollback_doc`；回滚生成新版本，历史只增不改。
- **测试**：`test_embeddings`、`test_pipeline_embedding`、`test_redis_guards`、`test_kb_versions`、`test_kb_api_versions`；CI 增加 Redis service 与 NumPy/FAISS 安装。

### 变更

- `/api/health` 增加 `retrieval_detail`（实际模式、索引状态、维度、降级原因）与 `kb`（活动版本、待审批数）。
- `/api/knowledge` 返回当前版本与待审批数；上传/删除在审批模式下返回 `pending` 与 `change_id`。
- `MIN_SCORE` 按检索模式给默认值：`embedding=0.38`、`vector/hybrid=0.30`、`bm25=0.5`。
- 核心仍零第三方依赖；NumPy / FAISS 为可选加速，缺失时退到纯 Python 精确内积。
- 本地 embedding 端点自动绕过 HTTP 代理，避免 127.0.0.1 被代理转发成 502。

## [1.2.0] - 2026-10-19

检索升级、动态示例问题与生产防护。

### 新增

- **向量召回 + 重排**：`VectorRerankRetriever` 作为默认检索器，向量召回候选后按词覆盖、长片段命中、BM25 与标题命中重排；`build_retriever` 工厂统一 `vector` / `bm25` / `hybrid`。
- **动态示例问题**：`src/suggest.py` 按知识库章节生成示例问题；新增 `GET /api/examples`。
- **未命中相似问题**：`no_answer` 返回「没有在文档中找到相关问题」并附 `similar_questions`；问答页可直接点击追问。
- **生产防护**：`src/guards.py` 提供幂等、按 IP 限流、审计、每日 token 上限、灰度与配置回滚；新增 `/api/admin/config`、`/api/admin/cost`、`/api/admin/rollback`、`/api/audit`。
- **测试**：新增 `tests/test_guards.py`。

### 变更

- **知识库独立成页**：新增 `/kb`，支持一次多选上传、搜索 / 类型筛选 / 排序、逐份出题与删除、重建索引。
- **首页精简**：只保留标题与「开始提问 / 上传文档」两个入口，移除说明段、示例问题与知识块指标。
- **问答页精简**：移除知识库侧栏、顶部标题与状态行；空态显示按当前文档生成的示例问题；离线抽取状态只在答案末尾显示。
- **看板瘦身**：移除知识库面板，保留概览、语义质量、用例、反馈与对话日志；引用覆盖率按百分比显示。
- **汇报页**：移除自我评价段落，改为功能清单、链路、评测结果与生产控制。

## [1.0.1] - 2026-10-18

收敛为独立项目：去掉与外部写作手册相关的一切表述，模型接入简化为单一 OpenAI 兼容端点。

### 变更

- **移除测试通道**：不再内置第二家服务商的端点与密钥变量；保留 `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`，换服务商只改环境变量。
- **移除 `--channel` 参数**：CLI 与服务端新增 `--model` / `--base-url` 单次覆盖；`eval_l3.py` 的异构裁判改用 `--judge-model`。
- **文档重写**：README / ARCHITECTURE / EVALUATION / SECURITY / 汇报页不再引用任何外部手册，评测报告中的模型标识改为中性占位（`model-a` / `model-b`）。
- **评测产物改名**：统一为 `report_llm.json` / `report_hard.json`，文件名不再带服务商标识。

## [1.0.0] - 2026-10-18

首个可下载、可复现的发布版本。

### 功能

- **RAG 主链路**：标题/条款感知切分 → BM25（中文二元组）→ 置信度闸门 → LLM 生成 → 引用校验/修复 → trace 落盘。
- **单一 OpenAI 兼容端点**：默认 DeepSeek，改 `LLM_BASE_URL` / `LLM_MODEL` 即可切到任意兼容服务；Key 只从环境变量读取。
- **离线降级**：未配置 Key 时自动走抽取式回答，全链路与评测仍可复现。
- **引用强制**：答案必须带有效 `[n]`；补不上引用则降级为可追溯答案，并标记 `no_citation`。
- **答不出转人工**：置信度低于阈值不硬答，写 handoff 工单（带 trace_id）。
- **知识库**：支持 `.md` / `.txt` / `.pdf` / `.docx`；上传即重建索引；PDF/DOCX 使用纯标准库解析，运行时零第三方依赖。
- **自动出题**：为上传文档生成评测用例（LLM 或唯一数值锚点兜底），删除文档后用例自动 skip。
- **四页 Web 原型**：首页、问答、评测看板、可分享汇报页；响应式布局、纯内联资源、断网可开。
- **评测体系**：
  - L1 确定性断言（行为/事实/安全/召回），基础集 26/26、难题集 13/13；
  - L3 LLM-as-Judge（忠实度/相关性/完整性）+ 负样本校准 + 异构裁判对比；
  - 召回评测 Recall@1/@4、MRR，四种检索配置对照。
- **可下载安装包**：`doc-qa-assistant-1.0.0.zip`，解压后双击 `start.bat` / `sh start.sh` 即可启动。

### 工程

- 设计系统抽到 `src/theme.py`，四个页面共用；版本号统一从 `VERSION` 读取。
- 新增 GitHub Actions CI（Python 3.11 / 3.13，离线冒烟 + 打包）。
- 修复检索报告 MRR 误读页面配置、切分函数闭包捕获循环变量等审查问题。
- 清理失败产物与本地绝对路径，仓库可直接克隆运行。

### 已知限制

- 不支持扫描件 PDF（需先 OCR）。
- Web 服务默认只绑定 `127.0.0.1`，没有鉴权与限流，不作为生产部署。
- 评测集规模较小，结论是方向性的；L3 分数存在裁判偏好。
