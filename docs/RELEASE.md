# 打包与发布

## 1. 版本号

唯一来源是仓库根目录的 `VERSION`。`src/version.py`、`/api/health`、页面角标、打包脚本都读它。

发版时：

1. 修改 `VERSION`（例如 `1.0.1`）；
2. 在 `CHANGELOG.md` 增加对应条目；
3. 重新打包。

## 2. 构建安装包

```bash
python tools/build_release.py
```

产物：

```
dist/doc-qa-assistant-<version>.zip
dist/SHA256SUMS.txt
```

包含：`src/`、`data/`（演示知识库与原始 PDF）、`docs/`、`tests/`、`tools/`、README、LICENSE、CHANGELOG、启动脚本、`.env.example`。
不包含：`.venv`、`logs/`、`dist/`、`__pycache__`、运行时生成的文档用例。

## 3. 验证安装包

不要只在源码目录里验证，必须解压后从零启动：

```bash
mkdir -p /tmp/docqa-test && cd /tmp/docqa-test
unzip <path>/doc-qa-assistant-1.0.0.zip
cd doc-qa-assistant-1.0.0
python -m src.server --port 8021 &
curl http://127.0.0.1:8021/api/health
curl -X POST http://127.0.0.1:8021/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"query":"稳盈系列的起购金额是多少"}'
```

期望：健康检查返回 `status=ok`、31 个知识块；问答返回 `behavior=answer` 且带引用。
再打开 `/`、`/dashboard`、`/report` 确认页面可渲染。

## 4. 发布到 GitHub

### 仓库首次创建

```bash
git init -b main
git add .
git commit -m "release: v1.0.0"
git remote add origin https://github.com/<owner>/doc-qa-assistant.git
git push -u origin main
```

仓库描述建议：

> 零依赖的文档问答（RAG）原型：强制引用、答不出转人工、L1/L3 双层评测与可分享汇报页。

Topics：`rag` `llm` `document-qa` `python` `bm25` `evaluation` `llm-as-judge` `deepseek` `zero-dependencies`。

### 创建 Release

GitHub CLI：

```bash
gh release create v1.0.0 \
  dist/doc-qa-assistant-1.0.0.zip \
  dist/SHA256SUMS.txt \
  dist/report.html \
  --title "v1.0.0 · 可下载的文档问答原型" \
  --notes-file CHANGELOG.md
```

或通过 API：先 `POST /repos/{owner}/{repo}/releases` 创建 release，再向
`https://uploads.github.com/repos/{owner}/{repo}/releases/{id}/assets?name=<file>` 上传资产。

## 5. 发布后检查

- Release 页面的 zip 能下载，大小与 SHA256 对得上；
- README 的下载链接指向 `releases/latest`；
- CI 在 main 上为绿色；
- 仓库内没有 `.env`、`logs/`、`dist/`、本地绝对路径。
