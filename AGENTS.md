# AGENTS.md —— 给智能体的接入说明

这个项目提供两件事，**都不要求你联网调模型**：

1. 文档问答（HTTP API，见 `GET /openapi.json`）
2. 个人笔记：把对话里值得留下的片段整理成 Markdown，存进用户的目录，任何智能体都能再读回来

笔记部分是重点。下面按「你是什么类型的智能体」给四条接入路径，任选一条即可。

## 一、MCP（推荐，支持 MCP 的客户端）

stdio 传输，由客户端拉起进程：

```json
{
  "mcpServers": {
    "agent-notes": {
      "command": "python",
      "args": ["-m", "src.notes.mcp_server"],
      "cwd": "/path/to/rag_assistant",
      "env": { "PYTHONPATH": "/path/to/rag_assistant", "NOTE_HOME": "~/agent-notes" }
    }
  }
}
```

Windows 上把 `python` 换成解释器绝对路径，`cwd` 用反斜杠或正斜杠都行。

也可以不拉进程，直接 POST 到已经在跑的主服务（v1.23 起）：

```bash
POST /mcp   Content-Type: application/json
{"jsonrpc":"2.0","id":1,"method":"tools/list"}
```

两条传输共用同一份 `handle()`，错误码与工具完全一致；通知类请求回 `202` 无正文，
支持 JSON-RPC 批量，`GET /mcp` 回 `405`。配了 `API_KEYS` 时 `/mcp` 与其他 `/api/*` 一样要带 Key。

可用工具 9 个：`save_conversation` / `search_notes` / `get_note` / `update_note` /
`delete_note` / `note_stats` / `export_notes` / `save_attachment` / `list_attachments`。
资源 2 类：`notes://schema`（格式契约）、`notes://index`（全部笔记的清单），
外加每个附件一条 `notes://asset/<笔记 id>/<文件名>`。

## 二、HTTP（任何能发请求的智能体）

```bash
POST   /api/notes                 # 保存；commit=false 只预览
GET    /api/notes?tag=&kind=&since=&limit=
GET    /api/notes/{id}            # 返回 rev
PATCH  /api/notes/{id}            # 必须带 base_rev
DELETE /api/notes/{id}?confirm=1
GET    /api/notes/stats
```

`GET /tools.json` 直接给出 7 个 OpenAI function calling 声明，塞进 `tools` 数组即可。
服务端配了 `API_KEYS` 时，记得带 `Authorization: Bearer <key>`。

### 直接改文件（v1.19.0）

笔记之外，存储区里的文本文件也能读写——这是「文件可自由修改」的接口面：

```bash
GET  /api/files/raw?path=notes/2026/10/xxx.md      # -> content / rev / size
PUT  /api/files/raw {path, content, base_rev}      # 缺 rev 428；被改过 409：先 GET 拿新 rev 再改
PUT  /api/files/raw {path, content, create:true}   # 新建；已存在 409
POST /api/files/open {path}                        # 交给用户的系统编辑器
```

- 路径是**相对存储区**的；绝对路径、`..`、符号链接逃逸都会被拒；
- 只允许 `.md .markdown .txt .json .jsonl .csv .yaml .yml`，单文件 ≤ 2 MB；
- `base_rev` 是内容哈希：别人（人或智能体）在这期间改过就拒绝覆盖，避免静默丢改动；
  覆盖已有文件**必须**带 rev（v1.19.1 起），新建要显式 `create:true`。

### 调用约定（v1.21.0）

- 写请求必须带 `Content-Type: application/json`，否则 415；服务端还会校验 `Host` 与 `Origin`。
- 浏览器发起的写请求要带 `X-Jiyi-Client: web`（页面里的 `fetch` 已统一包装，自动加）；
  curl / SDK / MCP 不带 `Origin`，不需要这个头。
- **鉴权按 `src/routing.py` 的表**：`open`（设置/健康/更新/契约）、`api`（其余 `/api/*`）、
  `admin`（`/metrics`、`/api/audit`、`/api/admin/*`、`/api/kb/approve|reject|rollback_doc`）。
  未登记的 `/api/*` 默认按 `api` 处理。配了 `API_KEYS` 后**读接口也要 Key**（含 `/api/source`、`/api/trace`）。
- **要改代码**：路由在 `src/handlers/`（`read.py` 只读、`write.py` 写入、`resources.py` 资源、
  `base.py` 闸门与通用动作、`app.py` 装配依赖）。`src/server.py` 只有入口，
  `tests/test_routing.py` 会断言它保持精简、且每个 `do_*` 第一句都过 `_guard`。
- 反向代理后面必须同时设 `ADMIN_TOKEN` + `API_KEYS` + `ALLOWED_HOSTS`：
  服务端只认 TCP 对端，从不读 `X-Forwarded-For`，否则谁都能冒充本机管理员。
- 500 响应默认只回异常类型（`DEBUG=on` 才带完整消息）；`/metrics` 的 `key` 标签是名字的哈希前缀。

### 会话记录（v1.19.0）

```bash
GET    /api/threads              # 列表（只有元数据，最近 60 条）
GET    /api/threads/{id}         # 正文
PUT    /api/threads/{id}         # 整条 upsert：{title, created, sid, turns}
DELETE /api/threads/{id}
```

会话存在 `<存储区>/threads/<id>.json`，和笔记同一个根目录。

### 备份与恢复（v1.20.0）

```bash
GET  /api/storage/backups                 # 列表
POST /api/storage/backup {note}           # 打包 notes/threads/exports → exports/backups/*.zip
POST /api/storage/restore {name, force}   # 覆盖前会再自动备份一份；force 缺省时遇已存在返回 409
```

### 不依赖浏览器的客户端（v1.20.0）

两个入口，共用同一套接口：

```bash
python -m src.client status                 # 终端客户端，任何 Python 都能跑
python -m src.desktop                       # 桌面窗口（需要标准库 Tkinter）
```

终端客户端还支持 `ask --save` / `ask --stream` / `notes` / `show` / `cat` / `write` /
`threads` / `backup` / `restore`。接口层在 `src/client_api.py`，脚本里可以直接复用：

```python
from src.client_api import Client
c = Client("http://127.0.0.1:8000")
print(c.ask("稳盈系列起购金额是多少")["answer"])

for event, payload in c.ask_stream("稳盈系列起购金额是多少"):   # SSE 逐字
    if event == "delta":
        print(payload["text"], end="", flush=True)
```

流式只有 `ask_stream()` 一个实现，桌面窗口与终端共用；遇到不支持流式的服务端，
桌面端会自动退回一次性请求。客户端会自动绕过系统代理访问 127.0.0.1（否则代理返回 502）。
**它记的是过程，不是结论**：值得留下的结论仍应通过 `save_conversation` 写成笔记。

## 三、命令行（只能执行命令的智能体）

```bash
export PYTHONPATH=/path/to/rag_assistant
python -m src.notes save --from conv.json --draft     # 先看整理成什么样
python -m src.notes save --from conv.json --kind decision --tags 税务
python -m src.notes list --tag 税务 --json
python -m src.notes get <id> --json
python -m src.notes export --out exports/all.html
```

## 四、直接读写文件（完全离线）

`NOTE_HOME`（默认 `~/agent-notes`）下 `notes/YYYY/MM/<id>.md` 就是全部内容，
格式见 `notes://schema` 或 `src/notes/schema_doc.py`。索引删了会自动重建。

**位置可能被界面改过**：用户在首启引导或「设置 → 存储」里选的目录写在 `data/app.json`，
优先级高于 `NOTE_HOME`。不确定当前用哪个目录时，先看 `data/app.json` 的 `notes.home`，
或调 `GET /api/settings` 读 `notes.home_effective`，不要假设还是默认值。

## 行为约定

- **先查再写**：用户问「上次那个结论」时先 `search_notes`（`query` 直接写自然语言，
  不必猜当时打的标签），不要凭记忆编。结果里的 `search.mode` 告诉你这次是语义排的还是只排了字面。
- **写前先读**：`update_note` 必须带 `get_note` 返回的 `rev`，否则拒绝——这是为了保护用户的手改。
- **删除要确认**：`delete_note` 需要显式 `confirm=true`；不确定就先问用户。
- **不要保存寒暄**：只存结论、步骤、决定、待办。
- **原文默认不存**：需要时才带 `keep_raw`。

## 给维护者的两句话

- 三个入口（MCP / HTTP / CLI）都只调 `src/notes/service.py`，不要在协议层写业务分支。
- 任何新字段先加到 `model.py` 常量与 `schema_doc.py`，再改 `contract.py` / `tools.py`，否则契约会漂。

## 前端资源的规矩（v1.18.0 起）

- **不要往 Python 里写 CSS/JS/HTML 字符串**。它们全在 `src/web/`：`base|settings|files|agent|ask|kb.css`、
  `side|settings|files|files_page|agent|ask|kb|theme|util.js`、对应 `.html` 片段与 `art.txt`。
  `theme.py` 只做资源装载与骨架拼接，`web_pages.py` 只做占位符替换。
- 改完跑 `python tools/check_frontend.py`：每个 `.js` 过 `node --check`，CSS 查括号与外部引用，
  拼装后的整页再逐段复检。`tests/test_frontend.py` 会拦住「又内联回去」（`theme.py` ≤ 260 行 / 20 KB）。
- 写资源文件必须 `newline=""`：Windows 上默认翻译换行，会把文件写成 CRLF，和 git 里对不上。
- 资源仍然内联进 HTML、不新增静态路由，所以**改完要重启进程**才生效；这不是缓存问题，别去清浏览器。

