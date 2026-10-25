# 技能包：zhiyuan-files（知源文件）

把「知源」的笔记能力交给智能体：列文件、搜内容、读全文、存对话、导出、打开文件页。
本页是交付说明；技能自己读的说明书在同目录的 [`skills/zhiyuan-files/SKILL.md`](../skills/zhiyuan-files/SKILL.md)。

## 一、基本信息

| 项 | 值 |
|---|---|
| 名称 | `zhiyuan-files`（显示名：知源文件） |
| 作用域 | 用户级，装在 `~/.workbuddy/skills/`，所有工作区可用 |
| 用途 | 读写本机笔记库（`NOTE_HOME`），并给用户一个可点的文件页地址 |
| 触发方式 | 由 `SKILL.md` 的 `description` 触发：提到「我的笔记 / 之前存过什么 / 文件页 / 把这段存成笔记 / 找关于 X 的笔记 / 导出笔记」时加载 |
| 参数输入 | 命令参数 + 环境变量 + `config.json`，优先级从高到低 |
| 依赖 | Python ≥ 3.11；运行时零第三方包 |
| 外部依赖 | 知源服务（默认 `http://127.0.0.1:8000`）——**只有存与导出需要**，读不依赖 |
| 自带文件 | 4 个：`SKILL.md`、`scripts/zy.py`、`references/api.md`、`assets/config.example.json` |

## 二、它到底做什么

| 动作 | 走哪条路 | 服务没起时 |
|---|---|---|
| 列文件 / 搜内容 / 读全文 | 直接读 `NOTE_HOME/notes/**/*.md` | **照常可用** |
| 存对话 | `POST /api/notes` | 若配了 `zhiyuan_home`，退回 `python -m src.notes save` 离线写；否则报错并给启动命令 |
| 导出 | `GET /api/notes/export` | 不可用（导出由服务生成），只报错，不假装成功 |
| 打开文件页 | 打印 / 拉起 `{base_url}/files` | 无浏览器就只打印地址 |

为什么读不依赖服务：笔记是普通 Markdown，服务只负责索引与生成。用户关掉服务也应该能翻自己的笔记。

## 三、参数输入

全局参数（放在子命令前后都行）：

| 参数 | 环境变量 | 配置文件键 | 默认值 | 说明 |
|---|---|---|---|---|
| `--base-url` | `ZHIYUAN_BASE_URL` | `base_url` | `http://127.0.0.1:8000` | 知源服务地址 |
| `--home` | `NOTE_HOME` | `note_home` | `~/agent-notes` | 笔记根目录 |
| `--zhiyuan-home` | `ZHIYUAN_HOME` | `zhiyuan_home` | 空 | 知源源码目录，服务没起时用于离线保存 |
| `--json` | — | — | 关 | 输出 JSON，便于程序消费 |

子命令与各自的参数：

```bash
zy.py doctor                                    # 自检：Python / 目录 / 可写 / 服务 / 文件页
zy.py list [--limit 20] [--tag T] [--kind K] [--status S]
zy.py search <词…> [--limit 20]                 # 多个词是「全部命中」
zy.py get <id 或标题片段>                        # 命中多篇会列出候选并以退出码 2 结束
zy.py save [--file conv.json] [--title T] [--tags a,b] [--kind K] [--status S] [--draft]
zy.py export [--format json|html] [--out PATH]
zy.py open [--page files|ask|kb] [--no-launch]
```

`save` 的输入格式：

```json
{ "messages": [
  { "role": "user", "text": "…" },
  { "role": "assistant", "text": "…" }
] }
```

也接受直接给数组。标题/标签/类型会放进请求体的 `hint` 对象（放顶层会被忽略，得到自动截断的 24 字标题）。

## 四、目录结构

仓库里（源码，随应用包一起发布）：

```
rag_assistant/
├── skills/zhiyuan-files/          # 技能源码，改了这里才算改
│   ├── SKILL.md                   # 给智能体读的说明书（frontmatter 决定何时触发）
│   ├── scripts/zy.py              # 唯一入口，零依赖
│   ├── references/api.md          # 接口、请求体、文件格式、错误码
│   └── assets/config.example.json # 配置模板
└── tools/install_skill.py         # 安装 / 卸载 / 检查
```

安装后（用户级）：

```
~/.workbuddy/skills/zhiyuan-files/   # 与上面四个文件一致，目录名不能改
~/.workbuddy/skills-backup/          # 覆盖或卸载时的备份，可手工恢复
```

## 五、安装

### 方式 A：一条命令（推荐）

```bash
cd rag_assistant
python tools/install_skill.py
```

它会：校验源码完整 → 已有旧版先备份到 `~/.workbuddy/skills-backup/zhiyuan-files-<时间>/` →
复制到 `~/.workbuddy/skills/zhiyuan-files` → 打印文件清单 → 跑一次 `doctor` 自检。

装到别处（例如只想临时试试）：

```bash
python tools/install_skill.py --target D:/tmp/skills
```

### 方式 B：从 Release 的 `zhiyuan-skill-<版本>.zip` 装

```bash
unzip zhiyuan-skill-1.16.0.zip -d ~/.workbuddy/skills/
# 解压后应为 ~/.workbuddy/skills/zhiyuan-files/SKILL.md，多一层目录就装错了
```

### 装完做什么

1. 在 WorkBuddy 的技能列表里刷新；多数版本会自动发现新目录，没看到就重启客户端。
2. 跑一次自检（见下节）。
3. 说一句「看看我的笔记」验证触发。

## 六、卸载

```bash
python tools/install_skill.py --uninstall
# 或手动：删掉 ~/.workbuddy/skills/zhiyuan-files 整个目录
```

卸载会先把目录复制到 `~/.workbuddy/skills-backup/zhiyuan-files-removed-<时间>/` 再删除，
想恢复就把它复制回 `~/.workbuddy/skills/`。卸载不影响笔记本身——笔记是 `NOTE_HOME` 下的普通文件。

## 七、配置示例

复制 `assets/config.example.json` 到技能目录下的 `config.json`：

```json
{
  "base_url": "http://127.0.0.1:8000",
  "note_home": "C:/Users/你的用户名/agent-notes",
  "zhiyuan_home": "D:/apps/zhiyuan-app-1.16.0"
}
```

三项都可省略，省略即默认值。`zhiyuan_home` 只在「服务没起、还要存笔记」时用到。

## 八、验证安装是否成功

```bash
python ~/.workbuddy/skills/zhiyuan-files/scripts/zy.py doctor
```

期望：

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

判定标准：

| 现象 | 结论 |
|---|---|
| 五项全 ✓、退出码 `0` | 装好了，读写都通 |
| 服务 / 文件页是 ✗，退出码 `1` | 装好了，但只能读；先启动知源（`start.bat` 或 `python -m src.server`） |
| 笔记目录 ✗ | `NOTE_HOME` 配错，或目录下没有 `notes/` |
| `doctor` 命令都跑不起来 | 装错层级（缺 `SKILL.md`）或 Python < 3.11 |

再做两件小事确认端到端：

```bash
python ~/.workbuddy/skills/zhiyuan-files/scripts/zy.py list        # 能看到笔记
python ~/.workbuddy/skills/zhiyuan-files/scripts/zy.py get <某个 id>  # 能读出正文
```

`--check` 用来看「装了没、和源码是否一致」，不会改任何文件：

```bash
python tools/install_skill.py --check
```

## 九、边界

- 只读写本机：不联网、不调用模型，存笔记的摘要是服务本地规则生成的。
- 删笔记要显式 `DELETE …?confirm=1`，文件进 `.trash/`；本技能没有提供删除命令，避免误删。
- 导出依赖服务；服务没起时不会退回「自己拼一个差不多的 HTML」——那会与页面导出的结果不一致。
- 同名内容会判重（按内容 hash），不会写第二篇；要重存先删旧的。
