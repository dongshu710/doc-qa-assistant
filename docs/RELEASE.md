# 打包与发布

## 1. 版本号

唯一来源是仓库根目录的 `VERSION`。`src/version.py`、`/api/health`、页面角标、打包脚本都读它。

发版时：

1. 修改 `VERSION`（例如 `1.4.0`）；
2. 在 `CHANGELOG.md` 增加对应条目；
3. 重新打包。

## 2. 构建安装包

```bash
python tools/build_release.py
```

产物：

```
dist/jiyi-app-<version>.zip      应用包（问答 + 笔记）
dist/jiyi-plugin-<version>.zip   插件包（只有笔记）
dist/jiyi-skill-<version>.zip    技能包（jiyi-files）
dist/SHA256SUMS.txt              三个包的 sha256
```

包含：`src/`、`data/`（演示知识库与原始 PDF）、`docs/`、`tests/`、`tools/`、README、LICENSE、CHANGELOG、启动脚本、`.env.example`。
不包含：`.venv`、`logs/`、`dist/`、`__pycache__`、运行时生成的文档用例。

## 3. 验证安装包

不要只在源码目录里验证，必须解压后从零启动：

```bash
mkdir -p /tmp/docqa-test && cd /tmp/docqa-test
unzip <path>/jiyi-app-<version>.zip
cd jiyi-app-<version>
python -m src.server --port 8021 &
curl http://127.0.0.1:8021/api/health
curl -X POST http://127.0.0.1:8021/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"query":"稳盈系列的起购金额是多少"}'
```

期望：健康检查返回 `status=ok`、31 个知识块；问答返回 `behavior=answer` 且带引用。
再打开 `/`、`/kb` 确认页面可渲染；`/insights`、`/dashboard`、`/report` 应 302 到 `/ask`。

笔记三通道也要各冒烟一条（都不需要模型）：

```bash
# 1) CLI
python -m src.notes --home /tmp/notes save --from conv.json --draft

# 2) HTTP
curl -s -X POST http://127.0.0.1:8021/api/notes -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"assistant","text":"结论：按 13% 执行。"}],"hint":{"title":"冒烟"}}'

# 3) MCP（逐行 JSON-RPC，用管道喂两条消息即可）
printf '%s\n%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | NOTE_HOME=/tmp/notes python -m src.notes.mcp_server
```

期望：`/api/notes` 返回 `201` 与 `path`；MCP 第二条返回 7 个工具名；`/kb#notes` 能看到这篇。

## 4. 发布到 GitHub

### 仓库首次创建

```bash
git init -b main
git add .
git commit -m "release: v1.4.0"
git remote add origin https://github.com/<owner>/doc-qa-assistant.git
git push -u origin main
```

仓库描述建议：

> 零依赖的文档问答（RAG）原型：强制引用、答不出明确说明、L1/L3 双层评测与可分享汇报页。

Topics：`rag` `llm` `document-qa` `python` `bm25` `evaluation` `llm-as-judge` `deepseek` `zero-dependencies`。

### 创建 Release

一条命令（推荐）：

```bash
python tools/build_release.py                    # 先出包
python tools/publish_release.py --tag v1.12.0    # 建 Release + 传 zip，正文自动摘 CHANGELOG
```

常用变体：

```bash
python tools/publish_release.py --all            # 补发所有已出包但还没建 Release 的版本
python tools/publish_release.py --tag v1.12.0 --dry-run   # 只看要做什么，不改远端
python tools/publish_release.py --tag v1.12.0 --no-asset  # 只同步正文
```

脚本行为：Release 正文取自 `CHANGELOG.md` 对应版本段落，附件是该版本三个包 + `SHA256SUMS.txt`
（README 承诺了「同页附 SHA256SUMS.txt」，不传就等于没兑现），正文末尾附
sha256 与下载直链；重复执行只同步正文、跳过已存在的附件，幂等；发布后自动把版本号最高的
Release 标为 latest（GitHub 默认把 latest 给最后创建的那个，批量补历史版本时会把新版挤下去，
导致 `/releases/latest/download/` 404）。

凭据：优先读 `GITHUB_TOKEN` / `GH_TOKEN`，没有就复用 git 凭据管理器里推代码的那份，不必另配。
只有两个接口：`POST /repos/{owner}/{repo}/releases` 建 release，
`POST https://uploads.github.com/repos/{owner}/{repo}/releases/{id}/assets?name=<file>` 传资产。

### `git push` 被代理掐断时

这台机器上 `github.com:443` 时常不通（`schannel: server closed abruptly`），
但 `api.github.com` 一直可用。于是把「推代码」拆成 REST 调用：

```bash
python tools/push_via_api.py --dry-run     # 先看会传哪些文件
python tools/push_via_api.py               # 提交信息默认取本地 HEAD
python tools/push_via_api.py -m "..."      # 或指定
```

它做的事：对比本地 `git ls-tree -r HEAD` 与远端树的 blob sha → 上传变化的 blob →
建 tree（`base_tree` 为远端树）→ 建 commit → 移动 `refs/heads/main`。

代价写在脚本头部：**远端 SHA 与本地不同**（GitHub 把 `+08:00` 规范成 `Z`），
所以推完要 `git fetch origin && git reset --hard origin/main` 才能继续正常 push。
网络上取不到对象时也可以直接接着用这个脚本——它每次都跟远端树比，不依赖本地 remote ref。

## 5. 发布后检查

- Release 页面的 zip 能下载，大小与 SHA256 对得上；
- README 的下载链接指向 `releases/latest`；
- CI 在 main 上为绿色；
- 仓库内没有 `.env`、`logs/`、`dist/`、本地绝对路径。
