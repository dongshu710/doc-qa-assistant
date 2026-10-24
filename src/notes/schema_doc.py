"""给智能体读的格式契约（MCP resource: notes://schema）。

单独立一份而不是拼字符串：模型读到的东西必须和代码里的校验一致，
所以字段名、可选值都从 model.py 的常量生成，改一处不会两边打架。
"""

from __future__ import annotations

from .model import KINDS, SCHEMA, SECTION_ORDER, STATUSES

SCHEMA_DOC = f"""# 笔记文件契约（{SCHEMA}）

一篇笔记 = 一个 Markdown 文件。文件是唯一真相，索引只是缓存；
你可以直接读、直接改，改完下次读取就会生效。

## 位置

```
NOTE_HOME（默认 ~/agent-notes）
├─ notes/YYYY/MM/<id>.md    笔记正文，路径即时间线
├─ index/notes.jsonl        派生索引，删了会自动重建
├─ assets/<id>/             附件（可选）
└─ .trash/                  软删除，可找回
```

## front matter（固定字段）

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema` | 是 | 固定 `note/v1` |
| `id` | 是 | 形如 `20261024-205142-5fc510`；文件名与它一致 |
| `title` | 是 | 单行标题，最长 120 字 |
| `created` / `updated` | 是 | ISO 8601，带时区 |
| `kind` | 是 | {' / '.join(KINDS)} |
| `status` | 是 | {' / '.join(STATUSES)} |
| `tags` | 否 | 字符串数组，最多 8 个 |
| `source` | 否 | 来源：`agent` / `model` / `session` / `messages` |
| `digest` | 是 | 摘要引擎：`rule` 或 `llm` |
| `hash` | 否 | 选中内容指纹，用于去重 |

未知字段原样保留，不会因为多一个键就报错。

## 正文小节

标准顺序：{' / '.join(SECTION_ORDER)}。缺哪节就省略哪节；多出来的小节也原样保留。

- `摘要`：一两句话说清这段对话留下了什么。
- `要点`：无序列表，每条一个事实。
- `决策`：已经定下来的结论。
- `待办`：`- [ ]` 开头的可执行项。
- `原文`：仅当显式要求保留时才有。
- `引用`：链接或出处。

## 容错（重要）

- front matter 缺失或写坏：不报错，降级为外部笔记（`external: true`），标题取首个 `#` 或文件名。
- 删掉整个 front matter 仍然能读、能列出。
- 索引被删：下次读取自动扫盘重建，条数以磁盘 `.md` 为准。
- 修改接口要求先读再写：`get` 会返回 `rev`（文件内容指纹），`update` 必须带回来，
  不一致返回冲突——这是为了不覆盖用户刚做的手改。
"""

HOME_README = """# 这里是你的个人笔记库

任何智能体（或你自己）都可以直接读写这个目录，不需要服务在跑。

## 目录

- `notes/YYYY/MM/*.md` —— 真正的内容。一篇笔记一个文件。
- `index/notes.jsonl` —— 加速用的索引。删掉没关系，下次读取会自动重建。
- `assets/` —— 附件。
- `exports/` —— 导出的单文件（HTML / JSON）。
- `.trash/` —— 删掉的笔记还在这里，改名移回 `notes/` 就能恢复。

## 给智能体的话

1. 先看 `index/` 或直接用命令行搜索，不要凭记忆回答「上次存过什么」。
2. 想改文件可以，但**改之前先读一遍**；服务端会用 `rev` 校验，避免覆盖别人的手改。
3. 新笔记按 `notes/YYYY/MM/<id>.md` 放，开头写 `---` front matter，字段见 `notes://schema`。
4. 不确定格式时，宁可调用工具，不要手写半个文件。

## 常用命令

```bash
python -m src.notes --home <这个目录> list --limit 20
python -m src.notes --home <这个目录> get <id>
python -m src.notes --home <这个目录> export --out exports/all.html
```
"""
