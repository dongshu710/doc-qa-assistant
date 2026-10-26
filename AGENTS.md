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

**位置可能被界面改过**：用户在页面「设置 → 存储」里选的自定义目录写在 `data/app.json`，
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

