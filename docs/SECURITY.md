# 安全说明

## 支持范围

本项目的安全目标是：

- 不泄露模型 Key；
- 不因为一句「忽略以上指令」就把系统提示或他人信息吐出来；
- 上传入口不被路径穿越、假后缀、超大文件打穿；
- 默认不对外网暴露，并提供基础的生产防护。

## 密钥处理

- 源码与仓库中**不含任何密钥**；`.env` 已在 `.gitignore` 中。
- Key 从两处读取：界面里填的落 `data/app.json`（该文件已 gitignore，写盘后按当前用户收紧权限：
  POSIX `0600`，Windows 去掉继承只授权当前用户）；也可以继续用环境变量 `LLM_API_KEY`（兼容 `DEEPSEEK_API_KEY`）。
  界面配置优先于环境变量。
- 日志与 trace 不记录请求头、Key、完整系统提示；`/api/settings` 只返回 `api_key_masked` 与 `api_key_set`。
- 前端页面不接触 Key，所有模型调用都在服务端完成。

如果你在自己的环境部署，建议使用系统密钥管理或容器 Secret，不要把 Key 写进启动脚本并提交。

## 请求来源校验（v1.19.1 起）

单机运行**不等于**安全：用户在浏览器里打开任意页面，那个页面可以向 `127.0.0.1` 发请求，
而对端 IP 就是本机——用 IP 判断「是不是自己人」永远为真。所以来源校验是独立一层
（`src/security.py`），不依赖「绑了 127.0.0.1」这个前提。

| 攻击 | 拦法 | 结果 |
|---|---|---|
| 跨站 POST 改配置 / 传语料 | 带 body 的写请求必须 `Content-Type: application/json`；同时校验 `Origin` 与 `Sec-Fetch-Site` | 403 / 415 |
| 浏览器发起的写请求 | 必须带 `X-Jiyi-Client: web`（跨站伪造它会触发预检，而本项目不开放跨域） | 403 |
| DNS rebinding 读走全文 | 所有请求（含 GET）的 `Host` 必须是回环地址或 `ALLOWED_HOSTS` 白名单 | 403 |
| 表单 / `fetch(no-cors)` 绕过 | 这两类只能发 `text/plain`、`urlencoded`、`multipart`，一律 415 | 415 |

三道检查统一在 `server.py::_guard(method, path)` 里执行，不分散到各 handler——
之前知识库上传/删除就是因为「各写各的」漏掉了鉴权。前端由 `util.js` 统一包了一层 `fetch`，
自动给写请求加 `X-Jiyi-Client`，新增接口不会忘。

不拦非浏览器客户端：curl / SDK / MCP 不带 `Origin`，也不受同源策略约束，拦了只会让接入变难
（它们也不需要带 `X-Jiyi-Client`）。
局域网访问需显式设置 `ALLOWED_HOSTS`（如 `192.168.1.9`），并同时配置 `API_KEYS`。

## 路由鉴权表（v1.21.0 起）

「记得在 handler 里加鉴权」不是可靠约束——知识库的上传/删除就是这样漏掉的（同目录的审批接口却要管理员）。
现在鉴权等级写在 `src/routing.py` 的一张表里，分发前由 `_guard()` 统一执行：

| 等级 | 含义 | 覆盖 |
|---|---|---|
| `open` | 明确开放 | `/api/settings`（Key 配错时的回退通道）、`/api/health`、`/api/update`、`/tools.json`、`/openapi.json`、页面 |
| `api` | 配了 `API_KEYS` 就要 Key | 笔记、会话、文件、存储、知识库读写、原文、提问记录、反馈、评测用例、`/api/ask` |
| `admin` | 本机或 `X-Admin-Token` | `/metrics`、`/api/audit`、`/api/admin/*`、`/api/kb/approve|reject|rollback_doc` |

两条规则值得记住：

- **未登记的 `/api/*` 默认按 `api` 处理**。漏登记最多让接口多要一个 Key，不会变成「谁都能读原文」。
- **读接口不再豁免**。`/api/source`（整段原文）、`/api/trace`（用户提问）以前只靠「绑了 127.0.0.1」，
  现在和其他数据面一样按表执行——GET 不等于公开。

测试 `tests/test_routing.py` 同时断言表本身（最长前缀优先、默认收紧）与分发函数
（六个 `do_*` 的第一次调用必须是 `_guard`），所以「绕过闸门」也会被测试挡住。

## 反向代理与来源判定（A6）

`_client()` 只认 TCP 对端的 `client_address`，**从不读 `X-Forwarded-For`**。这是刻意的：

- 伪造成本为零的请求头不能用来决定「是不是本机」，否则一个 `X-Forwarded-For: 127.0.0.1` 就能冒充管理员；
- 代价是：挂上反向代理后，所有请求看起来都来自 `127.0.0.1`，`_is_admin()` 的「本机即可」会整体失效。

所以**一旦放到反代后面，必须同时**：

1. 设置 `ADMIN_TOKEN`（此时管理员判定只认 `X-Admin-Token`，不再看来源 IP）；
2. 设置 `API_KEYS`（否则所有调用方都是匿名的同一个身份）；
3. 设置 `ALLOWED_HOSTS` 为外部实际访问的域名，否则 Host 校验会 403。

## 响应头与可观测面

- 所有响应带 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`；
  HTML 页面额外带 CSP（`default-src 'self'`、`frame-ancestors 'none'`、`base-uri 'none'`、`form-action 'none'`），
  页面不引任何外部脚本，所以不需要放宽。
- `/metrics` 归到 `admin` 等级；指标的 `key` 标签只放 Key 名字的 SHA-256 前 8 位，导出后也不泄露密钥名。
- 接口异常默认只回 `服务端异常：<异常类型>`，原文进服务端日志；排查时设 `DEBUG=on` 才回传完整消息
  （异常里常带绝对路径，不该出现在响应体里）。

## 已实现的输入防护

| 风险 | 处理 |
|---|---|
| 提示注入（忽略以上指令 / 输出系统提示） | 正则拦截，直接拒答，不进入检索与生成 |
| 越权读取他人信息 | 关键词拦截 + 拒答 |
| 金融合规（荐股、收益承诺） | `finance` profile 额外拒答规则；`generic` 可关闭 |
| 零宽字符 / 控制字符绕过 | 输入归一化后再匹配 |
| 超长输入 | 默认上限 500 字，超出转为追问 |
| 文件名路径穿越 | 显式拒绝 `/`、`\`、`..`，不做静默改名 |
| 假 PDF / DOCX 后缀 | 校验文件头，假后缀返回 400 |
| 超大文件 | 文本 512KB、PDF/DOCX 6MB 上限（413） |
| 扫描件 / 加密 PDF | 解析失败返回 422，并提示先 OCR / 解密 |

## 生产防护

| 能力 | 实现 |
|---|---|
| 限流 | 按客户端 IP（或 API Key）令牌桶，默认 5 rps / burst 10；超限 429 + `Retry-After` |
| API Key | `API_KEYS=名字:密钥,...`；支持 `Authorization: Bearer` 与 `X-API-Key`；常量时间比较；审计只记名字与末 4 位 |
| 幂等 | `Idempotency-Key` 在 TTL 内复用首次结果，避免重试重复计费 |
| 审计 | 问答摘要、上传/删除、审批/回滚、用例运行、灰度变更写入 `logs/audit.jsonl`；`LOG_SINK=stdout` 可输出 JSON 供集中采集 |
| 多实例状态 | 配置 `REDIS_URL` 后限流/幂等/成本跨实例共享；连接支持密码，失败回退本地 |
| 知识库审批 | `KB_APPROVAL=on` 时上传只进 `pending/`，管理员审批后才成为活动版本；审批/回滚需 admin |
| 成本上限 | 每日 token 预算，超限跳过模型调用并标记 `budget_exceeded` |
| 灰度 | 按调用方身份（API Key 或 IP）+ query 哈希稳定分流到灰度模型，比例可运行时调整 |
| 回滚 | 运行配置保留历史快照，`POST /api/admin/rollback` 恢复上一版 |
| 管理接口 | 设置 `ADMIN_TOKEN` 后需 `X-Admin-Token`；未设置时仅本机可调用（含审批/回滚） |

## 已知缺口

1. **业务接口鉴权默认关闭**：`API_KEYS` 为空时所有接口不做调用方认证（单机自用场景的默认值）。
   一旦配置 `API_KEYS`，读接口与写接口一样要求 Key（v1.21.0 起由 `src/routing.py` 统一执行，
   含 `/api/source`、`/api/trace`、`/api/knowledge` 等原先只看「是不是本机」的接口）。对外暴露必须配 `API_KEYS`。
2. **Redis 自身的安全**：连接支持密码，但没有内置 TLS 校验与 ACL 管理；`REDIS_URL` 必须只在内网可达，禁止裸奔到公网。Redis 失联时会回退进程内状态，此时多实例限流不再一致。
3. **trace 与审计会记录用户问题原文**：`logs/trace.jsonl`、`logs/audit.jsonl` 用于评测与排查。接入真实业务前需要脱敏（手机号、身份证、卡号）并设置保留期。
4. **上传解析在进程内完成**：没有沙箱与杀毒扫描。只接受文本型 PDF/DOCX；不要接受来源不明的文件。
5. **embedding 会把文档与问题发到模型端点**：若用外部 API，等于把知识库内容出网；敏感语料应部署内网 bge（TEI/Xinference），并在 `EMBEDDING_BASE_URL` 里指向内网地址。`EMBEDDING_API_KEY` 与 LLM Key 同等对待，不写日志。
6. **审批锁是本机文件锁**：多实例下审批应由单实例处理，或改用 Redis 分布式锁；否则两个实例同时审批可能各自生成版本（`state.json` 的 `os.replace` 保证不会写坏，但后写者覆盖先写者）。
5. **提示注入只能降低概率**：规则拦截覆盖常见句式，不保证 100%。模型输出仍应视为不可信内容。
6. **模型输出可能出错**：引用校验能降低「无出处」的比例，但不能保证事实一定正确；关键业务需人工复核。
7. **无 OCR**：扫描件 PDF 会被拒绝，而不是给出空答案。
8. **无多租户隔离**：所有请求共享同一知识库与索引。
9. **审计只保证本机落盘**：stdout 采集链路（Fluent Bit → Loki/ES）的丢失、篡改与保留期由日志平台负责；应用侧没有 WORM 存储。

## 部署建议

- 只在本机或内网使用；如需公网访问，放在反向代理后面并加认证与 HTTPS。
- 对外提供 API 时设置 `API_KEYS`（按调用方命名），并把用量与 `rag_api_cost_usd_total{key}` 接入告警；Key 轮换期间可让新旧 Key 同名并存。
- 设置 `ADMIN_TOKEN`，并限制 `/api/admin/*`、`/api/kb/approve|reject|rollback_doc` 的来源 IP。
- Redis 只监听内网，启用 `requirepass` / ACL，禁止公网暴露；`REDIS_TIMEOUT_S` 控制在 1~2s，避免故障时拖垮请求。
- 用内网 embedding 端点处理敏感语料；外部 API 场景先在数据合规侧确认出网范围。
- 设置 `LLM_TIMEOUT_S`、`LLM_MAX_RETRIES`、`WALL_CLOCK_BUDGET_S`、`DAILY_TOKEN_BUDGET`，避免单请求长时间占用与成本失控。
- 定期清理 `logs/`，不要把 trace 提交到仓库。
- 不要把 `.env`、`logs/`、`dist/` 打进公开镜像或压缩包（本项目 `.gitignore` 已处理）。

## 报告问题

发现安全问题请开 GitHub Issue，描述复现步骤与影响范围，不要附带真实密钥或个人数据。
