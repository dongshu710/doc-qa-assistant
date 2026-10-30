# 记忆文档 · 笔记插件（MCP）

让智能体把对话里值得留下的部分整理成结构化笔记，写进你自己的目录。
**这个包只做笔记**，不带文档问答、不带页面、不带索引——需要那些请下载「应用包」。

- 运行形态：MCP stdio（由客户端拉起进程，不占端口、不需要证书）
- 依赖：Python 3.11+，运行时零第三方依赖
- 存储：`NOTE_HOME`（默认 `~/agent-notes`）下的 `notes/YYYY/MM/<id>.md`，纯 Markdown
- 协议版本：`2024-11-05` / `2025-03-26` / `2025-06-18`

## 一、解压

解压到任意目录，路径里最好不要有空格：

```bash
unzip jiyi-plugin-1.15.0.zip -d ~/tools/
# → ~/tools/jiyi-plugin-1.15.0/
```

## 二、配置客户端

把下面这段合并进客户端的 MCP 配置（Claude Desktop 是 `claude_desktop_config.json`，
其他客户端见各自的「MCP Servers」设置）。三处路径改成你自己的：

```json
{
  "mcpServers": {
    "agent-notes": {
      "command": "python",
      "args": ["-m", "src.notes.mcp_server"],
      "env": {
        "PYTHONPATH": "/绝对路径/jiyi-plugin-1.15.0",
        "NOTE_HOME": "/绝对路径/agent-notes"
      }
    }
  }
}
```

Windows 示例：

```json
"PYTHONPATH": "D:\\tools\\jiyi-plugin-1.15.0",
"NOTE_HOME": "D:\\agent-notes"
```

改完重启客户端（或重载连接器）。列表里出现 `agent-notes` 且能看到 7 个工具，就通了。

## 三、它会做什么

| 工具 | 作用 |
|---|---|
| `save_conversation` | 把一段对话整理成一篇笔记（可先 `dry_run` 看草稿） |
| `search_notes` | 在已存笔记里按内容找（`query` 自然语言；也可只按标签/类型/日期筛） |
| `get_note` | 读一篇的全文 |
| `update_note` | 改标题 / 标签 / 状态 / 正文，需带 `base_rev` 防覆盖 |
| `note_stats` | 篇数、标签分布、最近更新时间 |
| `export_notes` | 导出全部（HTML / JSON） |
| `delete_note` | 删一篇，需显式 `confirm` |

外加两个资源：`notes://schema`（笔记格式说明）、`notes://index`（索引清单）。

笔记格式固定为六段正文（摘要 / 要点 / 决策 / 待办 / 原文摘录 / 元信息），
front matter 里带 `hash`，同样内容重复保存不会写第二篇。

## 四、命令行等价物

不想挂 MCP 也能直接用 CLI：

```bash
cd jiyi-plugin-1.15.0
PYTHONPATH=. python -m src.notes save --from conv.json --draft
PYTHONPATH=. python -m src.notes list --limit 20
PYTHONPATH=. python -m src.notes export --format html --out notes.html
```

## 五、常见问题

**Q：为什么在 WorkBuddy 的「更多选项」里找不到「添加按钮」？**
客户端工具栏不开放自定义按钮，任何插件都放不进去。要用的是「连接器 / MCP」那一栏：
添加自定义连接器 → 指向上面的 stdio 配置 → 点信任。人看的文件入口不在这里，
在应用包的页面右上角「文件」（或直接开 `http://127.0.0.1:8011/files`）。

**Q：能同时装应用包和插件包吗？**
可以，但只装一个就够。应用包已经带同一套笔记能力，插件包是给「只想要笔记、
不想跑整站」的人用的。两个包写同一个 `NOTE_HOME` 时不要同时开两个实例。

**Q：升级会丢笔记吗？**
不会。笔记是普通文件，升级只替换程序目录。升级前建议导出一次（`export_notes`）。
