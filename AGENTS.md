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

可用工具 7 个：`save_conversation` / `search_notes` / `get_note` / `update_note` /
`delete_note` / `note_stats` / `export_notes`。
资源 2 个：`notes://schema`（格式契约）、`notes://index`（全部笔记的清单）。

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

### 调用约定（v1.19.1）

- 写请求必须带 `Content-Type: application/json`，否则 415；服务端还会校验 `Host` 与 `Origin`。
- 浏览器发起的写请求要带 `X-Jiyi-Client: web`（页面里的 `fetch` 已统一包装，自动加）；
  curl / SDK / MCP 不带 `Origin`，不需要这个头。
- 配了 `API_KEYS` 后，知识库写接口（上传/删除）与笔记、会话、文件接口一样要带 Key；
  设置接口豁免，方便 Key 配错时改回来。

### 会话记录（v1.19.0）

```bash
GET    /api/threads              # 列表（只有元数据，最近 60 条）
GET    /api/threads/{id}         # 正文
PUT    /api/threads/{id}         # 整条 upsert：{title, created, sid, turns}
DELETE /api/threads/{id}
```

会话存在 `<存储区>/threads/<id>.json`，和笔记同一个根目录。
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

- **先查再写**：用户问「上次那个结论」时先 `search_notes`，不要凭记忆编。
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

