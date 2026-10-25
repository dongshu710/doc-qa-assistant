---
name: zhiyuan-files
description: 读写本机「知源」的笔记库并打开它的文件页。当用户说「看看我的笔记 / 之前存过什么 / 打开文件页 / 把这轮对话存成笔记 / 找一下关于某个主题的笔记 / 导出笔记」，或需要确认笔记目录里到底有哪些 Markdown 文件时使用。只读写本机文件与 localhost 接口，不联网。
agent_created: true
---

# 知源文件

## 这个技能能做什么

把「知源」的笔记能力交给智能体：列文件、按关键词搜、读一篇全文、把对话存成结构化笔记、导出 JSON/HTML、打开文件页。
读走本地 Markdown（服务没起也能看），写走本地 HTTP 接口（切分、摘要、去重由服务负责）。

## 什么时候用

- 用户提到「我的笔记」「之前存的内容」「文件页」「导出笔记」；
- 用户说「把这段存成笔记」「记一下这个结论」，需要落盘；
- 排查笔记库：篇数不对、想确认某篇在哪、NOTE_HOME 配到哪了；
- 需要给用户一个能点的地址看已存内容。

不要用它做文档问答（那是 `POST /api/ask` 的事，本技能不涉及）。

## 先自检

安装后先跑一次自检，五项全绿再往下走：

```bash
python <skill>/scripts/zy.py doctor
```

`<skill>` 是技能所在目录，安装后通常是 `~/.workbuddy/skills/zhiyuan-files`。
期望输出：

```
知源文件 · 自检
  ✓ Python     3.13.14（需要 ≥ 3.11）
  ✓ 笔记目录   C:\Users\你\agent-notes
  ✓ 可写       能写才能存新笔记
  ✓ 服务       http://127.0.0.1:8000 · v1.15.1
  ✓ 文件页      /files 可访问
  · 笔记篇数   2
结论：可用（读本地文件，写走服务）
```

- 退出码 `0` = 可读可写；`1` = 有硬性问题（Python 太老、目录缺失、服务没起）。
- 服务那一项红、其他绿：仍可读、可搜，但存与导出不可用，先让用户启动知源。

## 命令一览

所有命令都支持 `--json`（放命令前后都行），便于程序消费。

| 场景 | 命令 |
|---|---|
| 自检 | `zy.py doctor` |
| 最近 N 篇 | `zy.py list --limit 20` |
| 按标签/类型/状态筛 | `zy.py list --tag 产品 --kind qa --status final` |
| 搜内容（多个词是「全部命中」） | `zy.py search 赎回 到账` |
| 读全文（id 或标题片段） | `zy.py get 赎回到账时点` |
| 存对话 | `zy.py save --file conv.json --title "…" --tags 产品,规则` |
| 导出 | `zy.py export --format html --out notes.html` |
| 打开文件页 | `zy.py open`（`--page ask\|kb\|files`，`--no-launch` 只打印地址） |

把 `<skill>/scripts/zy.py` 简写成 `zy.py` 只为表格好读，实际执行要带完整路径。

## 保存一段对话

输入是标准输入或 `--file` 的 JSON，两种形态都接受：

```json
{ "messages": [
  { "role": "user", "text": "…" },
  { "role": "assistant", "text": "…" }
] }
```

或者直接给数组 `[{...}, {...}]`。

```bash
# 最省事：把对话写到临时文件再存
python <skill>/scripts/zy.py save --file conv.json --title "赎回规则确认" --tags 产品,赎回
# 管道
cat conv.json | python <skill>/scripts/zy.py save --tags 复盘
```

几个要点：

- **标题要显式给**。不给就按首条用户消息自动截断（24 字），用户会以为被吞了。
- 标题/标签/类型走请求体的 `hint` 对象；本脚本已经处理好，不用自己拼。
- 不带 `from=chat`：那是页面的标记，会被「储存对话内容」开关拦成 403。本技能走智能体通道。
- 相同内容会命中 `duplicate_of`，不会写第二篇；要重存先删旧的。
- 删笔记用 `DELETE /api/notes/{id}?confirm=1`，文件进 `.trash/`，可手工恢复。

## 两条通路与降级

| 动作 | 主通路 | 失败时 |
|---|---|---|
| 列表 / 搜索 / 读全文 | 直接读 `NOTE_HOME/notes/**/*.md` | 目录不存在 → 空列表 + 说明 |
| 保存 | `POST /api/notes` | 服务不可用且给了 `zhiyuan_home` → 用 `python -m src.notes save` 离线写；都没有则报错并提示启动命令 |
| 导出 | `GET /api/notes/export` | 导出依赖服务生成，失败只报错，不假装成功 |
| 打开页面 | 打印 / 拉起 `{base_url}/files` | 无浏览器就只打印地址 |

为什么读不依赖服务：笔记就是普通 Markdown，服务只是索引与生成器。用户关掉服务也应该能翻自己的笔记。

## 配置

优先级：**命令行 > 环境变量 > `config.json` > 默认值**。

| 项 | 命令行 | 环境变量 | config.json | 默认 |
|---|---|---|---|---|
| 服务地址 | `--base-url` | `ZHIYUAN_BASE_URL` | `base_url` | `http://127.0.0.1:8000` |
| 笔记根目录 | `--home` | `NOTE_HOME` | `note_home` | `~/agent-notes` |
| 知源源码目录（离线保存用） | `--zhiyuan-home` | `ZHIYUAN_HOME` | `zhiyuan_home` | 空 |

`config.json` 放在技能目录下，示例见 `assets/config.example.json`。三项都可省略，
省略即默认值——少一个必填项就少一类安装失败。

## 常见问题

**服务没起**：`doctor` 会明确写「只能读，存与导出需要服务」。让用户双击 `start.bat`，
或 `python -m src.server`；端口不是 8000 就加 `--port` 并同步 `--base-url`。

**端口没人听却返回 502**：本机代理会把「连接被拒」包装成 502。脚本把 5xx 一律当「服务不可用」，
不会把它当成一次成功响应。

**标题被截成 24 字**：说明 `hint.title` 没传到（放到了请求体顶层）。用本脚本的 `--title` 不会踩到。

**中文乱码**：Windows 控制台默认 cp936。脚本已 `reconfigure(encoding="utf-8")`；
自己写调用时也要这么做，或设 `PYTHONUTF8=1`。

**想确认装没装成功**：`doctor` 五项全绿且退出码 0；再用 `list` 能看到笔记，用 `get` 能读出正文。

## 资源

- `scripts/zy.py`：唯一入口，零第三方依赖，Python ≥ 3.11。
- `references/api.md`：接口、请求体、文件格式、错误码、为什么不重试 POST。
- `assets/config.example.json`：配置模板。
