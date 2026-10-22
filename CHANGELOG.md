# Changelog

遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与语义化版本。

## [1.7.0] - 2026-10-22

P1 七项：传输优化、日志轮转尾读、判域前置、对比度与字号、未命中反馈与答案元信息、会话历史与导出、表格入库。

### 新增

- **HTTP 传输层**：`Handler.protocol_version = "HTTP/1.1"` + 定长响应，连接可复用；`_send` 统一做 gzip（`/ask` 51 KB → 15.5 KB）、弱 ETag 协商与 `304`；JSON 接口 `Cache-Control: no-store`；补 `do_HEAD`（原为 501）。
- **日志轮转与尾读**：新增 `src/jsonl.py`，`append_line` 按 `LOG_MAX_BYTES`（默认 16 MB）/ `LOG_KEEP` 轮转；`tail_lines` 从文件尾按 64 KB 反向读取。`audit.tail`、`metrics.summarize`、`/api/trace`、`/api/audit` 全部改用。37 MB trace 实测 11 ms（全量读 86 ms）。
- **未命中反馈**：`no_answer` 卡片收「应该怎么答 + 哪份文档有答案」，`/api/feedback` 新增 `behavior` / `query` / `expected` / `document` / `session_id` / `kb_version` 字段并返回 `need`。
- **答案元信息**：脚注显示知识库版本、引用条数、引用覆盖率、检索分；未命中显示「最高分 / 阈值」（`min_score` 随响应返回）。
- **会话历史与导出**：`localStorage` 保留最近 40 轮，刷新恢复最近 12 轮；新增「导出 Markdown」（问题 / 答案 / 引用 / 元信息）；清空对话同步清理本地记录。
- **表格入库**：新增 `src/table_text.py`，标准库解析 `.xlsx`（zip + sharedStrings + worksheet）与 `.csv` / `.tsv`（UTF-8 → GB18030 兜底，分隔符自动嗅探），每个工作表转 Markdown 表格；上传、版本库、关键词抽取全链路打通。
- **测试**：`test_http_transport`（保活 / gzip / 304 / HEAD / SSE）、`test_jsonl_log`（跨块尾读 / 截断行 / 轮转 / 大文件延迟）、`test_table_ingest`（xlsx 夹具 / 编码 / 竖线转义 / 切分 / 关键词）、`test_retrieval_order`（域外 0 次扩展 / 扩展更差不替换 / 扩展异常降级）；CI 增加四步。

### 变更

- **判域前置、扩展后置**：先用原问题检索并过置信度闸门，通过后才做查询扩展；扩展结果只在分数更高时替换原结果。域外问题少 1 次 LLM + 1 次 embedding；扩展失败降级为原问题检索（`expansion_error` 写 trace），不再 500。
- **对比度与字号**：`--muted` 改为 `#4a5468`（7.61:1）、`--faint` 改为 `#667085`（白底 4.97:1 / 浅底 4.65:1，原为 2.58:1 / 2.41:1）；`theme.py` 与 `web_pages.py` 中 69 处小于 12px 的字号统一抬到 12px；移动端输入框 16px，避免 iOS 聚焦缩放。
- **表格行按整行入库**：Markdown 表格不再按管道符切成清单，条目片段改为 `表头：值 · 表头：值`，
  直出答案不会再把 `| 产品 | 1000 元 |` 原样吐给用户；表头单元格指向第一行数据（问「起购金额」给一条真实记录）。
- **扫描件提示**：`pdf_ingest.assess` 的告警改为可操作步骤（先 OCR、另存为 docx/txt 再上传），失败响应带 `need_ocr`。
- 上传支持 `.xlsx` / `.csv` / `.tsv`；知识库页与上传提示同步。
- 版本升到 1.7.0。

## [1.6.0] - 2026-10-21

P0 五项落地：流式输出、多轮会话、引用原文、审批界面、知识库接口预计算；未命中不再转人工。

### 新增

- **流式问答**：`POST /api/ask/stream` 以 SSE 返回 `delta` / `replace` / `final`；生成层解析上游 `stream:true`，检测 `[DONE]` 缺失（连接被掐断）并整体降级为抽取式；前端边收边渲染，发送按钮在生成中变为「停止」，`AbortController` 可中断。
- **多轮会话**：`src/sessions.py` 保存最近 3 轮（30 分钟 TTL、最多 1000 会话）；`session_id` 随请求上报，追问（「那 R2 呢」）会拼上上一轮问题，独立问题不拼；`POST /api/session/clear` 清理。
- **引用原文**：citation 增加 `doc_id` / `chunk_index` / `version` / `snippet`；新增 `GET /api/source?doc=&chunk=`，问答页点击 `[1]` 打开右侧原文抽屉并高亮命中行。
- **审批界面**：知识库页展示待审批变更、文件动作与风险提示；`GET /api/kb/change?id=` 返回统一 diff，可直接通过/驳回；每份文档新增「历史」入口与文档级回滚；配置 `ADMIN_TOKEN` 时可在面板内填写令牌（存 sessionStorage）。
- **知识库关键词预计算**：`KeywordIndex._build_doc_terms()` 在建索引时按文档缓存关键词；`/api/knowledge` 与 `/api/keywords` 不再逐文档全量扫描（500 文档/2.5 万条目实测 506 ms → 0.26 ms，构建一次 10 ms）。
- **测试**：`test_session`（上下文改写/TTL/轮数）、`test_stream`（SSE 事件顺序/多轮/未命中）、`test_generator_stream`（真实 SSE 解析/用量/截断替换）；CI 增加三步。

### 变更

- **未命中不再转人工**：`no_answer` 统一返回「无法找到答案。」；删除 `/api/handoff`、工单表单、`logs/handoff.jsonl` 与页面转人工入口；相似问题保留。
- `/api/ask` 响应增加 `session_id` / `context_query` / `turn` / `kb_version`；审计记录 `session_id` 与 `stream`。
- 知识库页每行新增「历史」按钮；问答页引用由纯文本改为可点击按钮。
- 版本升到 1.6.0。

## [1.5.0] - 2026-10-21

关键词直出精度治理：命中之后加否定/极性、解释型意图、单文档收敛四道闸门，匹配改为倒排索引。

### 修复

- **否定越界**：「我不爱吃香菜」同时返回「不吃的食物」与「爱吃的食物」，答案自相矛盾。现在命中位置前 3 字内的否定词会让正向条目本次失效，并记 `negated`。
- **极性冲突**：「我不喜欢的运动是什么」会把「运动：每周三次游泳」当成答案。现在同族条目（去掉极性后的核心词相同）按问句极性取舍，中性/反向条目记 `polarity_conflict`。
- **度量碎片入库**：「每次 1 小时」被当成条目。现在 `每次/每天 + 数字` 这类度量短语不进索引；同时修正「过滤后只剩一项导致整行降级为单值标签、真条目一起丢失」的连带问题。
- **引用编号错位**：多处命中同一原文时，`citations` 里有多余条目而正文没有对应 `[n]`。现在先去重再编号，直出答案内联 `[n]`。

### 新增

- **四道闸门**：`KEYWORD_GUARD=on`（默认）启用否定作用域、极性冲突、解释型意图（为什么/怎么/区别/流程）与单文档收敛；`off` 回到 1.4.0 行为，便于 A/B。`KEYWORD_MULTI_DOC=on` 可放开跨文档直出。
- **核心词别名**：「喜欢的音乐」补「音乐」、「讨厌的天气」补「天气」，只在第一人称提问时生效，避免「明天天气」被截胡。
- **可观测**：响应新增 `keyword_gate`、`keyword_rejected`、`keyword_polarity`；指标新增 `rag_keyword_rejected_total{reason}`、`rag_keyword_gate_total{gate}`；审计日志记录闸门与被挡词。
- **倒排索引**：匹配从「遍历全部条目 × 别名」改为「枚举问句子串查字典」。`tests/bench_keyword.py` 实测 6750 条目下单次 0.018 ms（线性扫描 14.25 ms，约 800×），2 万条目约 2800×；结果与线性实现一致（`test_keyword_precision` 有对照）。
- **测试与评测**：`tests/test_keyword_precision.py` 覆盖否定、极性、意图、度量噪声、单文档、开关回退、索引一致性、引用对齐；`tests/eval_keyword.py` 以 13 条应直出 + 9 条不应直出标注集输出指标（当前 13/13 命中、0 误伤）。CI 增加这两步。

### 变更

- `/api/keywords` 与 `/api/health.keywords` 增加 `guard`、`multi_doc`、`by_polarity`。
- `tools/keyword_demo.py` 默认问题加入否定与解释型用例，逐条打印闸门与被挡原因。
- README 4.9 节补充四道闸门、配置项与边界；版本升到 1.5.0。

## [1.4.0] - 2026-10-21

新增「关键词直出」路径：清单/标签类条目命中时本地返回，不调用任何模型；页面进一步精简。

### 新增

- **关键词索引**：`src/keywords.py` 从清单项、表格行、`标签：值`、`## 关键词` 段抽条目，附带原文片段、出处与权重；章节名仅用于展示，不触发直出。
- **本地直出**：`pipeline.ask` 在检索前先做关键词匹配，命中即返回原文片段 + 引用，结果标 `path=keyword`、`mode=keyword_local`、`api_called=false`，不经过查询扩展 / embedding / 生成 / 补引用。
- **API 整理（可选）**：`KEYWORD_LLM=auto` 且配置 Key 时，每份新增/变更文档调用一次模型生成摘要与同义说法；`term` 必须在原文出现，snippet 一律从原文截取，解析失败保留本地结果。
- **接口**：`GET /api/keywords`、`GET /api/keywords?name=`、`POST /api/keywords/rebuild`；`/api/knowledge` 返回每份文档的关键词与数量，`/api/health` 返回关键词索引状态。
- **指标**：`rag_keyword_hit_total`、`rag_answer_path_total{path}`、`rag_local_answer_total`；响应头 `X-Answer-Path`，审计字段 `path` 与 `api_called`。
- **演示与测试**：`data/demo/小a的生活习惯.md`、`tools/keyword_demo.py`、`tests/test_keywords.py`（含假端点请求数断言）、`tests/test_keyword_api.py`。

### 变更

- 知识库页新增「关键词」列，点击展开词表与摘要；说明文案同步直出规则。
- 问答页命中时显示「本地直出」标签、命中词与「未调用模型」状态，不展示通道/模型。
- 首页右侧示意卡改为两条回答路径（关键词本地直出 / 检索生成），移除原浏览器窗口示意；知识库说明精简为 4 条。
- 版本升到 1.4.0；README 新增 4.9 节，架构文档与 CI 同步。

## [1.3.0] - 2026-10-20

检索升级为真 embedding、多实例状态外置、知识库版本化与审批。

### 新增

- **真 embedding 检索**：`src/embeddings.py` 接入 OpenAI 兼容 `/embeddings`（bge 同协议），批请求、429/5xx 退避重试、墙钟上限、维度探测与内容缓存；`RETRIEVAL=embedding` 启用。
- **向量索引**：`src/vector_store.py` 提供纯 Python / NumPy / FAISS（flat、ivf）三种后端，manifest 记录模型、维度、语料指纹与后端；指纹不匹配自动重建。
- **索引工具**：`tools/build_index.py` 支持全量重建、后端选择与构建后抽查。
- **多实例状态**：`src/redis_client.py`（零依赖 RESP2）+ `guards` 的 Redis 限流（Lua 令牌桶）、幂等（SET NX PX）、日 token 预算（INCRBY）；Redis 故障回退本地并暴露健康状态。
- **集中观测**：`GET /metrics` 输出 Prometheus 指标（请求、延迟直方图、限流、幂等重放、降级、token、版本）；`LOG_SINK=stdout|both` 输出结构化审计 JSON；新增 `deploy/prometheus.yml`、`deploy/fluent-bit.conf` 与多实例说明。
- **知识库版本库**：`src/kbstore.py` 管理 `data/kb/versions/vNNNN`、`pending` 变更、`state.json` 活动指针；上传先暂存，审批后生成新版本。
- **审批与文档级回滚**：`GET /api/kb/versions`、`/api/kb/changes`、`/api/kb/doc_history`，`POST /api/kb/approve|reject|rollback_doc`；回滚生成新版本，历史只增不改。
- **测试**：`test_embeddings`、`test_pipeline_embedding`、`test_redis_guards`、`test_kb_versions`、`test_kb_api_versions`；CI 增加 Redis service 与 NumPy/FAISS 安装。

### 变更

- `/api/health` 增加 `retrieval_detail`（实际模式、索引状态、维度、降级原因）与 `kb`（活动版本、待审批数）。
- `/api/knowledge` 返回当前版本与待审批数；上传/删除在审批模式下返回 `pending` 与 `change_id`。
- `MIN_SCORE` 按检索模式给默认值：`embedding=0.38`、`vector/hybrid=0.30`、`bm25=0.5`。
- 核心仍零第三方依赖；NumPy / FAISS 为可选加速，缺失时退到纯 Python 精确内积。
- 本地 embedding 端点自动绕过 HTTP 代理，避免 127.0.0.1 被代理转发成 502。

## [1.2.0] - 2026-10-19

检索升级、动态示例问题与生产防护。

### 新增

- **向量召回 + 重排**：`VectorRerankRetriever` 作为默认检索器，向量召回候选后按词覆盖、长片段命中、BM25 与标题命中重排；`build_retriever` 工厂统一 `vector` / `bm25` / `hybrid`。
- **动态示例问题**：`src/suggest.py` 按知识库章节生成示例问题；新增 `GET /api/examples`。
- **未命中相似问题**：`no_answer` 返回「没有在文档中找到相关问题」并附 `similar_questions`；问答页可直接点击追问。
- **生产防护**：`src/guards.py` 提供幂等、按 IP 限流、审计、每日 token 上限、灰度与配置回滚；新增 `/api/admin/config`、`/api/admin/cost`、`/api/admin/rollback`、`/api/audit`。
- **测试**：新增 `tests/test_guards.py`。

### 变更

- **知识库独立成页**：新增 `/kb`，支持一次多选上传、搜索 / 类型筛选 / 排序、逐份出题与删除、重建索引。
- **首页精简**：只保留标题与「开始提问 / 上传文档」两个入口，移除说明段、示例问题与知识块指标。
- **问答页精简**：移除知识库侧栏、顶部标题与状态行；空态显示按当前文档生成的示例问题；离线抽取状态只在答案末尾显示。
- **看板瘦身**：移除知识库面板，保留概览、语义质量、用例、反馈与对话日志；引用覆盖率按百分比显示。
- **汇报页**：移除自我评价段落，改为功能清单、链路、评测结果与生产控制。

## [1.0.1] - 2026-10-18

收敛为独立项目：去掉与外部写作手册相关的一切表述，模型接入简化为单一 OpenAI 兼容端点。

### 变更

- **移除测试通道**：不再内置第二家服务商的端点与密钥变量；保留 `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`，换服务商只改环境变量。
- **移除 `--channel` 参数**：CLI 与服务端新增 `--model` / `--base-url` 单次覆盖；`eval_l3.py` 的异构裁判改用 `--judge-model`。
- **文档重写**：README / ARCHITECTURE / EVALUATION / SECURITY / 汇报页不再引用任何外部手册，评测报告中的模型标识改为中性占位（`model-a` / `model-b`）。
- **评测产物改名**：统一为 `report_llm.json` / `report_hard.json`，文件名不再带服务商标识。

## [1.0.0] - 2026-10-18

首个可下载、可复现的发布版本。

### 功能

- **RAG 主链路**：标题/条款感知切分 → BM25（中文二元组）→ 置信度闸门 → LLM 生成 → 引用校验/修复 → trace 落盘。
- **单一 OpenAI 兼容端点**：默认 DeepSeek，改 `LLM_BASE_URL` / `LLM_MODEL` 即可切到任意兼容服务；Key 只从环境变量读取。
- **离线降级**：未配置 Key 时自动走抽取式回答，全链路与评测仍可复现。
- **引用强制**：答案必须带有效 `[n]`；补不上引用则降级为可追溯答案，并标记 `no_citation`。
- **答不出转人工**：置信度低于阈值不硬答，写 handoff 工单（带 trace_id）。
- **知识库**：支持 `.md` / `.txt` / `.pdf` / `.docx`；上传即重建索引；PDF/DOCX 使用纯标准库解析，运行时零第三方依赖。
- **自动出题**：为上传文档生成评测用例（LLM 或唯一数值锚点兜底），删除文档后用例自动 skip。
- **四页 Web 原型**：首页、问答、评测看板、可分享汇报页；响应式布局、纯内联资源、断网可开。
- **评测体系**：
  - L1 确定性断言（行为/事实/安全/召回），基础集 26/26、难题集 13/13；
  - L3 LLM-as-Judge（忠实度/相关性/完整性）+ 负样本校准 + 异构裁判对比；
  - 召回评测 Recall@1/@4、MRR，四种检索配置对照。
- **可下载安装包**：`doc-qa-assistant-1.0.0.zip`，解压后双击 `start.bat` / `sh start.sh` 即可启动。

### 工程

- 设计系统抽到 `src/theme.py`，四个页面共用；版本号统一从 `VERSION` 读取。
- 新增 GitHub Actions CI（Python 3.11 / 3.13，离线冒烟 + 打包）。
- 修复检索报告 MRR 误读页面配置、切分函数闭包捕获循环变量等审查问题。
- 清理失败产物与本地绝对路径，仓库可直接克隆运行。

### 已知限制

- 不支持扫描件 PDF（需先 OCR）。
- Web 服务默认只绑定 `127.0.0.1`，没有鉴权与限流，不作为生产部署。
- 评测集规模较小，结论是方向性的；L3 分数存在裁判偏好。
