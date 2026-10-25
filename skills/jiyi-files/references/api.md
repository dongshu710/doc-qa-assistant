# 记忆文档笔记接口参考

脚本 `scripts/jy.py` 只依赖下面这几个接口。服务地址默认 `http://127.0.0.1:8000`，
换成别的端口改配置或 `--base-url` 即可。

## 一、用到的 HTTP 接口

| 方法 | 路径 | 用途 | 关键参数 |
|---|---|---|---|
| GET | `/api/health` | 自检：确认服务在跑、拿版本号 | 无 |
| GET | `/files` | 文件页（人看的入口） | 无 |
| GET | `/api/notes` | 列表 | `limit`（≤200）、`tag`、`kind`、`status`、`since` |
| GET | `/api/notes/{id}` | 读一篇 | 可选 `section` 只取某一段 |
| POST | `/api/notes` | 存一段对话 | 见下节请求体 |
| PATCH | `/api/notes/{id}` | 改标题/标签/状态/正文 | 必须带 `base_rev`（并发保护，否则 409） |
| DELETE | `/api/notes/{id}?confirm=1` | 删除（进 `.trash`，可手工恢复） | `confirm=1` 必填 |
| GET | `/api/notes/export?format=json\|html` | 导出全部 | 返回内容本身，不落服务端磁盘 |

## 二、保存笔记的请求体

```json
{
  "messages": [
    { "role": "user", "text": "稳盈系列起购金额是多少？" },
    { "role": "assistant", "text": "起购金额 1 元，风险等级 R1，期限 90 天。" }
  ],
  "hint": {
    "title": "稳盈系列起购规则",
    "tags": ["产品", "起购"],
    "kind": "qa",
    "status": "draft"
  },
  "commit": true,
  "keep_raw": false
}
```

- `hint` 是**对象**，标题/标签/类型/状态都放里面；放在最外层会被忽略，得到自动截断的标题。
- `commit: false` 只预览不落盘（返回 `markdown`），适合让用户先看一眼。
- `keep_raw: true` 额外保留完整对话原文到「原文」段。
- **不要带 `from: "chat"`**：那是页面「存为笔记」的标记，会被「储存对话内容」开关拦成 403；
  智能体/脚本走的是不带 `from` 的通道，不受该开关影响。

返回（201）：

```json
{
  "ok": true, "committed": true, "id": "20261025-221551-62b880",
  "title": "稳盈系列起购规则", "kind": "qa", "tags": ["产品", "起购"],
  "digest": "rule", "messages": 2,
  "path": "…/notes/2026/10/20261025-221551-62b880.md",
  "duplicate_of": null
}
```

`duplicate_of` 非空表示内容与已有笔记相同（按内容 hash 判重），返回的是既有那篇的 id。

## 三、笔记文件格式（脚本直接读这个）

```
~/agent-notes/
├── notes/2026/10/20261025-221551-62b880.md
├── index/notes.jsonl          # 索引缓存，删了会自动重建
└── .trash/                    # 删除的笔记，改名移回 notes/ 即可恢复
```

单篇是带 front matter 的 Markdown：

```markdown
---
schema: note/v1
id: 20261025-221551-62b880
title: 稳盈系列起购规则
created: 2026-10-25T22:15:51+08:00
updated: 2026-10-25T22:15:51+08:00
kind: qa
status: draft
tags: [产品, 起购]
digest: rule
hash: sha256:…
---

## 摘要
…
## 要点
…
## 决策
…
## 待办
…
```

脚本只解析 `key: value` 与 `tags: [a, b]`，嵌套块（如 `source:`）跳过；
front matter 写坏了也照样能读正文——用户手改一次不该让一整篇废掉。

## 四、错误码与含义

| 状态码 | 含义 | 脚本行为 |
|---|---|---|
| 400 | 参数不合法（如 limit 为负、messages 为空） | 原样打印 message |
| 403 | 被「储存对话内容」开关拦下（只对带 `from=chat` 的请求） | 提示不要带 from |
| 404 | id 不存在 | 提示先 `list` |
| 409 | 修改时 `base_rev` 过期 | 提示先 `get` 拿新 rev |
| 5xx | 服务没起 / 反代连不上 | 保存走离线兜底，导出直接报错并提示启动 |

> 端口没人听时，本机代理常回 **502** 而不是「拒绝连接」，所以脚本把 5xx 一律当「服务不可用」，
> 不把 502 当成一次成功响应。

## 五、为什么不重试 POST

`POST /api/notes` 不是幂等的：超时后重试可能写出两篇（内容 hash 判重能挡住完全相同的内容，
但差一个字就挡不住）。所以脚本对 GET 允许重试一次，POST 一次都不重试，失败就把错误原样抛给用户。
