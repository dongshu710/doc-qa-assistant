# 贡献指南

这是一个小体量的 RAG 原型，欢迎提 Issue 和 PR。改动请尽量小而聚焦。

## 本地运行

```bash
git clone <repo-url>
cd doc-qa-assistant
python -m src.server --port 8000
```

要求 Python 3.11+，运行时零第三方依赖。未配置模型 Key 时自动进入离线抽取模式。

## 改动前

- 修 bug：先补一条能复现的评测用例（`tests/eval_cases*.jsonl`），再改代码。
- 改检索/生成：先跑 `tests/eval_run.py` 与 `tests/eval_retrieval.py`，确认没有把已通过的用例改坏。
- 改页面：检查 1440px 与 520px 两个宽度，不要引入外部 CDN。

## 提交前自检

```bash
python -m compileall -q src tests tools
python tests/test_pdf_text.py
python tests/test_kb_api.py
python tests/test_pdf_upload.py
python tests/test_docx_upload.py
python tests/test_server.py
python tools/build_release.py
```

以上全部在离线模式下可跑，不需要任何 Key。CI 会在 Python 3.11 / 3.13 上重复这些检查。

## 代码约定

- 注释解释「为什么」，不复述「做了什么」。
- 外部调用必须有显式超时、重试与降级路径，不允许静默失败。
- 不要把 Key、真实客户数据、`logs/`、`.env` 提交进仓库。
- 新增依赖必须写版本号，并在 PR 里说明为什么标准库不够用。

## PR 描述

请写清楚：问题、改动、验证方式（命令与结果）、已知风险。UI 改动附截图。
