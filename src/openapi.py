"""OpenAPI 3.0 描述：对外集成只需要这一份机器可读契约。

手写而不是从路由自动生成：路由是 `if/elif` 字符串分发，自动生成要么引入
框架依赖，要么写一套脆弱的反射；接口数量有限，手写反而更准。改动接口时
同步改这里，`tests/test_auth_openapi.py` 会校验路径与关键字段不漂移。

按主题拆成 `_info` / `_tags` / `_paths_*` / `_components`：原来是一个 280 行的
字典字面量，加一个接口要在里面翻半天，`build_spec` 只负责组装。
"""
from __future__ import annotations

from .notes.contract import notes_paths


def _err(desc: str) -> dict:
    return {"description": desc,
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}


def _sec(secured: list) -> dict:
    return {"security": secured} if secured else {}


def _info(version: str, secured: list) -> dict:
    return {
        "title": "记忆文档 API",
        "version": version,
        "description": (
            "只依据知识库作答，逐条返回引用；资料不足时返回 no_answer，不编造。\n\n"
            "鉴权：" + ("已启用 API Key，`/api/ask` 与 `/api/ask/stream` 必须携带 "
                      "`Authorization: Bearer <key>` 或 `X-API-Key: <key>`。"
                      if secured else
                      "当前未启用 API Key（`API_KEYS` 为空），问答接口按客户端 IP 限流。")
        ),
        "contact": {"name": "项目维护者"},
        "license": {"name": "MIT"},
    }


def _tags() -> list:
    return [
        {"name": "问答", "description": "检索、生成与反馈"},
        {"name": "知识库", "description": "文档、版本与审批"},
        {"name": "笔记", "description": "对话整理成个人笔记：保存、查询、修改、删除"},
        {"name": "运维", "description": "健康检查与指标"},
    ]


def _paths_qa(secured: list) -> dict:
    return {
        "/api/ask": {
            "post": {
                "tags": ["问答"], "summary": "提问（一次性返回）",
                "operationId": "ask",
                **_sec(secured),
                "parameters": [{
                    "name": "Idempotency-Key", "in": "header", "required": False,
                    "schema": {"type": "string", "maxLength": 128},
                    "description": "同一 Key 在 TTL 内复用首次结果，避免重试重复计费",
                }],
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/AskRequest"}}}},
                "responses": {
                    "200": {"description": "回答（answer / no_answer / ask_clarify / refuse）",
                            "content": {"application/json": {
                                "schema": {"$ref": "#/components/schemas/AskResult"}}}},
                    "401": _err("缺少或无效的 API Key"),
                    "429": _err("触发限流，按 Retry-After 重试"),
                },
            }
        },
        "/api/ask/stream": {
            "post": {
                "tags": ["问答"], "summary": "提问（SSE 流式）",
                "operationId": "askStream",
                **_sec(secured),
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/AskRequest"}}}},
                "responses": {
                    "200": {"description": (
                        "text/event-stream：`delta` 增量文本、`replace` 替换全文、"
                        "`final` 完整结果（同 AskResult）、`error` 错误"),
                        "content": {"text/event-stream": {"schema": {"type": "string"}}}},
                    "401": _err("缺少或无效的 API Key"),
                    "429": _err("触发限流"),
                },
            }
        },
        "/api/session/clear": {
            "post": {
                "tags": ["问答"], "summary": "清空会话上下文",
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"type": "object", "required": ["session_id"], "properties": {
                        "session_id": {"type": "string", "maxLength": 64}}}}}},
                "responses": {"200": {"description": "已清空"}},
            }
        },
        "/api/feedback": {
            "post": {
                "tags": ["问答"], "summary": "提交答案反馈 / 未命中线索",
                "requestBody": {"required": True, "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/FeedbackRequest"}}}},
                "responses": {"200": {"description": "已记录"}},
            }
        },
    }


def _paths_ops() -> dict:
    return {
        "/api/health": {
            "get": {
                "tags": ["运维"], "summary": "健康检查",
                "responses": {"200": {"description": "服务、索引、知识库与防护状态",
                                      "content": {"application/json": {
                                          "schema": {"type": "object"}}}}},
            }
        },
        "/api/reload": {
            "post": {"tags": ["运维"], "summary": "重建索引（默认后台执行）",
                     "responses": {"200": {"description": "rebuilding=true 表示已排队"}}}
        },
        "/api/metrics": {
            "get": {"tags": ["运维"], "summary": "业务聚合指标",
                    "responses": {"200": {"description": "请求量、延迟、降级与 token"}}}
        },
        "/metrics": {
            "get": {"tags": ["运维"],
                    "summary": "Prometheus 文本格式指标（需管理员，含成本与 Key 标签）",
                    "responses": {"200": {"description": "text/plain; version=0.0.4"},
                                  "403": _err("需要管理员令牌或本机访问")}}
        },
    }


def _paths_kb() -> dict:
    return {
        "/api/knowledge": {
            "get": {
                "tags": ["知识库"], "summary": "文档列表与块数",
                "responses": {"200": {"description": "当前活动版本的文件与关键词概览"}},
            }
        },
        "/api/source": {
            "get": {
                "tags": ["知识库"], "summary": "按引用定位原文",
                "parameters": [
                    {"name": "doc", "in": "query", "required": True,
                     "schema": {"type": "string"}},
                    {"name": "chunk", "in": "query", "required": True,
                     "schema": {"type": "integer", "minimum": 0}},
                ],
                "responses": {"200": {"description": "原文块"},
                              "404": _err("引用不存在")},
            }
        },
        "/api/kb/versions": {
            "get": {"tags": ["知识库"], "summary": "版本列表",
                    "responses": {"200": {"description": "版本与 manifest"}}}
        },
        "/api/kb/changes": {
            "get": {"tags": ["知识库"], "summary": "变更审批记录",
                    "parameters": [{"name": "status", "in": "query", "required": False,
                                    "schema": {"type": "string",
                                               "enum": ["pending", "approved", "rejected"]}}],
                    "responses": {"200": {"description": "变更列表"}}}
        },
        "/api/kb/change": {
            "get": {"tags": ["知识库"], "summary": "待审批变更的文本 diff",
                    "parameters": [{"name": "id", "in": "query", "required": True,
                                    "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "逐文件 diff"},
                                  "404": _err("变更不存在")}}
        },
        "/api/kb/approve": {
            "post": {"tags": ["知识库"], "summary": "通过变更并生成新版本（需管理员）",
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": {"type": "object", "required": ["change_id"], "properties": {
                             "change_id": {"type": "string"},
                             "note": {"type": "string", "maxLength": 200}}}}}},
                     "responses": {"200": {"description": "新版本号与新索引状态"},
                                   "403": _err("需要管理员令牌"),
                                   "409": _err("状态冲突或基线版本已过期")}}
        },
        "/api/kb/reject": {
            "post": {"tags": ["知识库"], "summary": "驳回变更（需管理员）",
                     "responses": {"200": {"description": "已驳回"},
                                   "403": _err("需要管理员令牌")}}
        },
        "/api/kb/rollback_doc": {
            "post": {"tags": ["知识库"], "summary": "按文档回滚（需管理员）",
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": {"type": "object",
                                    "required": ["name", "to_version"], "properties": {
                                        "name": {"type": "string"},
                                        "to_version": {"type": "string"}}}}}},
                     "responses": {"200": {"description": "生成回滚版本"},
                                   "403": _err("需要管理员令牌"),
                                   "409": _err("版本或文档不存在")}}
        },
        "/api/knowledge/upload": {
            "post": {"tags": ["知识库"], "summary": "上传 .md / .txt",
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": {"type": "object", "required": ["name", "content"],
                                    "properties": {
                                        "name": {"type": "string", "maxLength": 80},
                                        "content": {"type": "string", "maxLength": 524288},
                                        "note": {"type": "string"}}}}}},
                     "responses": {"200": {"description": "已暂存或已入库"},
                                   "400": _err("文件名或内容不合法")}}
        },
        "/api/knowledge/upload_file": {
            "post": {"tags": ["知识库"], "summary": "上传 PDF / DOCX / XLSX / CSV（base64）",
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": {"type": "object", "required": ["name", "data_b64"],
                                    "properties": {
                                        "name": {"type": "string"},
                                        "data_b64": {"type": "string",
                                                     "description": "文件 base64，解码后 ≤ 6 MB"}}}}}},
                     "responses": {"200": {"description": "解析并入库"},
                                   "400": _err("文件头不匹配"),
                                   "422": _err("解析失败或扫描件需 OCR")}}
        },
        "/api/knowledge/upload_pdf": {
            "post": {"tags": ["知识库"],
                     "summary": "上传 PDF（`upload_file` 的旧别名，行为完全一致）",
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": {"type": "object", "required": ["name", "data_b64"],
                                    "properties": {
                                        "name": {"type": "string"},
                                        "data_b64": {"type": "string",
                                                     "description": "文件 base64，解码后 ≤ 6 MB"}}}}}},
                     "responses": {"200": {"description": "解析并入库"},
                                   "400": _err("文件头不匹配"),
                                   "422": _err("解析失败或扫描件需 OCR")}}
        },
        "/api/knowledge/delete": {
            "post": {"tags": ["知识库"], "summary": "删除文档",
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": {"type": "object", "required": ["name"], "properties": {
                             "name": {"type": "string"}}}}}},
                     "responses": {"200": {"description": "已删除"},
                                   "404": _err("文件不存在")}}
        },
    }


def _x_internal() -> dict:
    """页面专用端点标记。

    为什么这些也要写进契约：`routing.allowed_methods()` 从这份规格里读
    路径 → 方法表，用来把「方法用错」判成 405 而不是 404。它们以前列在
    `routing._EXTRA_METHODS` 那张补丁表里，结果补丁表自己漂了——
    `/api/storage/usage`、`/api/storage/cleanup` 两个端点早已不存在，
    而真存在的 `/api/storage/restore` 反倒没登记（回 404 而不是 405）。
    现在路径只有这一份来源。
    """
    return {"x-internal": True}


def _no_body(desc: str) -> dict:
    return {"200": {"description": desc}}


def _paths_admin() -> dict:
    """管理面。级别在 `routing.RULES` 里是 ADMIN：要令牌，或从本机访问。"""
    denied = {"403": _err("需要管理员令牌（ADMIN_TOKEN），或从本机访问")}
    return {
        "/api/admin/config": {
            "get": {"tags": ["运维"], "summary": "当前灰度与运行时配置", **_x_internal(),
                    "responses": {"200": {"description": "grayscale / canary / overrides"}}},
            "post": {"tags": ["运维"], "summary": "调整灰度比例与模型", **_x_internal(),
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": {"type": "object", "properties": {
                             "canary_percent": {"type": "integer", "minimum": 0, "maximum": 100},
                             "canary_model": {"type": "string"}}}}}},
                     "responses": {"200": {"description": "新配置与 revision"},
                                   **denied}},
        },
        "/api/admin/rollback": {
            "post": {"tags": ["运维"], "summary": "回滚上一版运行时配置", **_x_internal(),
                     "responses": {"200": {"description": "回滚后的配置"}, **denied}},
        },
        "/api/admin/cost": {
            "get": {"tags": ["运维"], "summary": "当日 token 消耗与预算余量", **_x_internal(),
                    "responses": {"200": {"description": "used / budget / ratio"}}},
        },
        "/api/audit": {
            "get": {"tags": ["运维"], "summary": "审计日志尾条", **_x_internal(),
                    "parameters": [{"name": "limit", "in": "query", "required": False,
                                    "schema": {"type": "integer", "minimum": 1,
                                               "maximum": 200, "default": 20}}],
                    "responses": {"200": {"description": "按时间倒序的动作记录"}, **denied}},
        },
    }


def _paths_data() -> dict:
    """评测数据面：用例、运行、关键词、轨迹、反馈。"""
    return {
        "/api/cases": {
            "get": {"tags": ["运维"], "summary": "评测用例概览与上一次运行结果", **_x_internal(),
                    "responses": {"200": {"description": "curated / feedback / docs / last_run"}}},
        },
        "/api/cases/run": {
            "post": {"tags": ["运维"], "summary": "跑一遍 L1 用例（同步）", **_x_internal(),
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": {"type": "object", "properties": {
                             "scope": {"type": "string",
                                       "enum": ["all", "curated", "feedback", "docs"],
                                       "default": "all",
                                       "description": "docs 依赖 tests/eval_cases_docs.jsonl，"
                                                      "文件不存在时会正常返回 total=0"}}}}}},
                     "responses": {"200": {"description": "passed / total / failed[] / run_at"}}},
        },
        "/api/cases/from_doc": {
            "post": {"tags": ["运维"], "summary": "从文档自动出题", **_x_internal(),
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": {"type": "object", "required": ["doc_id"], "properties": {
                             "doc_id": {"type": "string"},
                             "count": {"type": "integer", "minimum": 1, "maximum": 20}}}}}},
                     "responses": {"200": {"description": "生成的用例（已落盘）"}}},
        },
        "/api/cases/from_feedback": {
            "post": {"tags": ["运维"], "summary": "把用户反馈转成评测用例", **_x_internal(),
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": {"type": "object", "required": ["trace_id"], "properties": {
                             "trace_id": {"type": "string"}}}}}},
                     "responses": {"200": {"description": "新增用例数"}}},
        },
        "/api/examples": {
            "get": {"tags": ["问答"], "summary": "首页示例问题", **_x_internal(),
                    "parameters": [{"name": "n", "in": "query", "required": False,
                                    "schema": {"type": "integer", "minimum": 1,
                                               "maximum": 8, "default": 4}}],
                    "responses": {"200": {"description": "示例问题列表"}}},
        },
        "/api/keywords": {
            "get": {"tags": ["知识库"], "summary": "关键词库总览或单文档视图", **_x_internal(),
                    "parameters": [{"name": "name", "in": "query", "required": False,
                                    "schema": {"type": "string"},
                                    "description": "给定时返回该文档的词条，否则返回全部"}],
                    "responses": {"200": {"description": "docs / summary"},
                                  "404": _err("文档不存在或未生成关键词")}},
        },
        "/api/keywords/rebuild": {
            "post": {"tags": ["知识库"], "summary": "重建关键词库", **_x_internal(),
                     "responses": {"200": {"description": "重建计数与耗时"}}},
        },
        "/api/trace": {
            "get": {"tags": ["运维"], "summary": "调用轨迹尾条", **_x_internal(),
                    "parameters": [{"name": "limit", "in": "query", "required": False,
                                    "schema": {"type": "integer", "minimum": 1,
                                               "maximum": 200, "default": 20}}],
                    "responses": {"200": {"description": "ts / query / behavior / latency_ms"}}},
        },
        "/api/feedback/list": {
            "get": {"tags": ["问答"], "summary": "反馈记录尾条", **_x_internal(),
                    "parameters": [{"name": "limit", "in": "query", "required": False,
                                    "schema": {"type": "integer", "minimum": 1,
                                               "maximum": 200, "default": 20}}],
                    "responses": {"200": {"description": "反馈条目"}}},
        },
        "/api/kb/doc_history": {
            "get": {"tags": ["知识库"], "summary": "单文档的版本历史", **_x_internal(),
                    "parameters": [{"name": "name", "in": "query", "required": True,
                                    "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "各版本与是否仍在使用"},
                                  "400": _err("文档名为空或库里没有这份文档")}},
        },
    }


def _paths_client() -> dict:
    """页面与本地客户端专用：设置、存储区文件、会话记录、MCP。

    全部标 `x-internal`——它们不是给外部集成用的（`/api/settings` 里的
    `llm.api_key` 是明文凭据，`/api/files/raw` 能读写存储区任意文件）。
    登记进契约只是为了让方法表有单一来源，不改变它们的权限等级。
    """
    return {
        "/api/settings": {
            "get": {"tags": ["运维"], "summary": "当前设置（配了 Key 且未带 Key 时脱敏）",
                    **_x_internal(), "responses": {"200": {"description": "设置全量"}}},
            "post": {"tags": ["运维"], "summary": "写入设置", **_x_internal(),
                     "responses": {"200": {"description": "新设置与 notes_reloaded"},
                                   "403": _err("非本机修改需要 X-Admin-Token")}},
        },
        "/api/settings/setup": {
            "get": {"tags": ["运维"], "summary": "首启引导状态", **_x_internal(),
                    "responses": {"200": {"description": "needed / current"}}},
            "post": {"tags": ["运维"], "summary": "选存储区并完成引导", **_x_internal(),
                     "responses": {"200": {"description": "存储区已生效"}}},
        },
        "/api/settings/pick-folder": {
            "post": {"tags": ["运维"], "summary": "唤起系统目录选择框", **_x_internal(),
                     "responses": {"200": {"description": "选中的路径，取消时为空"}}},
        },
        "/api/settings/test": {
            "post": {"tags": ["运维"], "summary": "测试模型连通性", **_x_internal(),
                     "responses": {"200": {"description": "ok / latency_ms / error"}}},
        },
        "/api/settings/open": {
            "post": {"tags": ["运维"], "summary": "在系统文件管理器中打开存储区", **_x_internal(),
                     "responses": {"200": {"description": "打开与否"}}},
        },
        "/api/settings/mcp": {
            "get": {"tags": ["运维"], "summary": "导出 MCP 客户端配置", **_x_internal(),
                    "responses": {"200": {"description": "claude / vscode 两种片段"}}},
            "post": {"tags": ["运维"], "summary": "写入 MCP 客户端配置", **_x_internal(),
                     "responses": {"200": {"description": "写入的文件"}}},
        },
        "/api/settings/mcp/install": {
            "post": {"tags": ["运维"], "summary": "安装 MCP 配置到指定客户端", **_x_internal(),
                     "responses": {"200": {"description": "写入结果"}}},
        },
        "/api/settings/notes/migrate": {
            "post": {"tags": ["运维"], "summary": "把旧位置的笔记搬到当前存储区", **_x_internal(),
                     "responses": {"200": {"description": "copied / skipped / failed"},
                                   "400": _err("路径非法或旧位置没有 notes 目录")}},
        },
        "/api/settings/storage/clean": {
            "post": {"tags": ["运维"], "summary": "清理历史版本（保留 N 个）", **_x_internal(),
                     "responses": {"200": {"description": "删除数与释放字节"},
                                   "400": _err("keep 不是 0 或正整数")}},
        },
        "/api/files/raw": {
            "get": {"tags": ["运维"], "summary": "读存储区里的一个文件", **_x_internal(),
                    "parameters": [{"name": "path", "in": "query", "required": True,
                                    "schema": {"type": "string"},
                                    "description": "相对存储区的路径"}],
                    "responses": {"200": {"description": "content / rev"},
                                  "404": _err("文件不存在")}},
            "put": {"tags": ["运维"], "summary": "写存储区里的一个文件", **_x_internal(),
                    "requestBody": {"required": True, "content": {"application/json": {
                        "schema": {"type": "object", "required": ["path", "content"],
                                   "properties": {
                                       "path": {"type": "string"},
                                       "content": {"type": "string"},
                                       "base_rev": {"type": "string",
                                                    "description": "覆盖时必须与当前 rev 一致，否则 428"},
                                       "create": {"type": "boolean"}}}}}},
                    "responses": {"200": {"description": "写入后的 rev"},
                                  "409": _err("文件已被删除"), "428": _err("缺少 base_rev")}},
        },
        "/api/files/open": {
            "post": {"tags": ["运维"], "summary": "用系统默认程序打开文件", **_x_internal(),
                     "responses": {"200": {"description": "已交给系统"}}},
        },
        "/api/files/open-folder": {
            "post": {"tags": ["运维"], "summary": "打开存储区所在目录", **_x_internal(),
                     "responses": {"200": {"description": "目录路径"}}},
        },
        "/api/storage/backups": {
            "get": {"tags": ["运维"], "summary": "备份清单", **_x_internal(),
                    "responses": {"200": {"description": "name / at / files / bytes"}}},
        },
        "/api/storage/backup": {
            "post": {"tags": ["运维"], "summary": "立即备份整个存储区", **_x_internal(),
                     "responses": {"200": {"description": "备份名与字节数"}}},
        },
        "/api/storage/restore": {
            "post": {"tags": ["运维"], "summary": "从备份恢复（恢复前自动再备份）", **_x_internal(),
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": {"type": "object", "required": ["name"], "properties": {
                             "name": {"type": "string"}, "force": {"type": "boolean"}}}}}},
                     "responses": {"200": {"description": "restored / pre_backup"},
                                   "409": _err("目标非空且未加 force")}},
        },
        "/api/threads": {
            "get": {"tags": ["问答"], "summary": "会话列表", **_x_internal(),
                    "responses": {"200": {"description": "items（按更新时间倒序）"}}},
            "post": {"tags": ["问答"], "summary": "批量导入会话", **_x_internal(),
                     "responses": {"200": {"description": "imported"}}},
        },
        "/api/threads/{id}": {
            "get": {"tags": ["问答"], "summary": "读一条会话", **_x_internal(),
                    "parameters": [{"name": "id", "in": "path", "required": True,
                                    "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "会话内容"},
                                  "404": _err("会话不存在")}},
            "put": {"tags": ["问答"], "summary": "写入会话（按 id 覆盖）", **_x_internal(),
                    "parameters": [{"name": "id", "in": "path", "required": True,
                                    "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "写入后的元信息"}}},
            "delete": {"tags": ["问答"], "summary": "删除会话", **_x_internal(),
                       "parameters": [{"name": "id", "in": "path", "required": True,
                                       "schema": {"type": "string"}}],
                       "responses": {"200": {"description": "已删除"}}},
        },
        "/api/threads/import": {
            "post": {"tags": ["问答"], "summary": "导入会话（同 `/api/threads` 的 POST）",
                     **_x_internal(),
                     "responses": {"200": {"description": "imported"}}},
        },
        "/mcp": {
            "get": {"tags": ["笔记"], "summary": "Streamable HTTP 下行流（SSE）", **_x_internal(),
                    "responses": {"200": {"description": "text/event-stream：connected / ping"},
                                  "405": _err("未要求 event-stream 时只接受 POST")}},
            "post": {"tags": ["笔记"], "summary": "MCP JSON-RPC（与 stdio 同一份实现）",
                     **_x_internal(),
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": {"type": "object",
                                    "description": "单条或批量 JSON-RPC 请求；通知回 202"}}}},
                     "responses": {"200": {"description": "JSON-RPC 响应（要 SSE 时是单条 message）"},
                                   "202": _no_body("通知类请求，无正文")}},
        },
    }


def _paths_meta() -> dict:
    """自述与契约本身。这几条都是 open 级：不需要 Key 也能读。"""
    return {
        "/openapi.json": {
            "get": {"tags": ["运维"], "summary": "本规格", **_x_internal(),
                    "responses": {"200": {"description": "OpenAPI 3.0.3 文档"}}},
        },
        "/tools.json": {
            "get": {"tags": ["笔记"], "summary": "function calling 工具清单", **_x_internal(),
                    "responses": {"200": {"description": "OpenAI 兼容的 tools 数组"}}},
        },
        "/api/update/check": {
            "get": {"tags": ["运维"], "summary": "检查新版本（只查不装）", **_x_internal(),
                    "parameters": [{"name": "force", "in": "query", "required": False,
                                    "schema": {"type": "boolean", "default": False}}],
                    "responses": {"200": {"description": "latest / url / has_update"}}},
        },
        "/api/l3": {
            "get": {"tags": ["运维"], "summary": "L3 语义评分摘要", **_x_internal(),
                    "responses": {"200": {"description": "available / avg / gate"}}},
        },
    }


def _components() -> dict:
    return {
        "securitySchemes": {
            "bearerAuth": {"type": "http", "scheme": "bearer",
                           "description": "API_KEYS 中配置的密钥"},
            "apiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key",
                           "description": "与 Bearer 二选一"},
        },
        "schemas": {
            "AskRequest": {
                "type": "object", "required": ["query"],
                "properties": {
                    "query": {"type": "string", "maxLength": 500,
                              "example": "稳盈 Plus 30 天的起购金额是多少？"},
                    "session_id": {"type": "string", "maxLength": 64,
                                   "description": "同一会话内保留最近 3 轮，用于指代式追问"},
                    "request_id": {"type": "string", "maxLength": 64,
                                   "description": "也可用 Idempotency-Key 头"},
                },
            },
            "Citation": {
                "type": "object",
                "properties": {
                    "ref": {"type": "integer", "description": "正文中的 [n]"},
                    "title": {"type": "string"}, "section": {"type": "string"},
                    "doc_id": {"type": "string"},
                    "chunk_index": {"type": "integer",
                                    "description": "文档内序号（从 0 开始），"
                                                   "直接用于 GET /api/source?doc=&chunk="},
                    "version": {"type": "string", "description": "知识库版本，如 v0005"},
                    "snippet": {"type": "string", "description": "命中片段"},
                },
            },
            "AskResult": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "behavior": {"type": "string",
                                 "enum": ["answer", "no_answer", "ask_clarify", "refuse"]},
                    "mode": {"type": "string",
                             "enum": ["llm", "extractive", "extractive_fallback"]},
                    "path": {"type": "string", "enum": ["rag", "keyword"]},
                    "citations": {"type": "array",
                                  "items": {"$ref": "#/components/schemas/Citation"}},
                    "citation_coverage": {"type": "number", "minimum": 0, "maximum": 1},
                    "similar_questions": {"type": "array", "items": {"type": "string"}},
                    "retrieval_score": {"type": "number"},
                    "min_score": {"type": "number", "description": "当前检索模式的阈值"},
                    "kb_version": {"type": "string"},
                    "session_id": {"type": "string"},
                    "trace_id": {"type": "string"},
                    "request_id": {"type": "string"},
                    "latency_ms": {"type": "number"},
                    "usage": {"type": "object", "description": "模型 token 用量"},
                    "cost_usd": {"type": "number", "description": "按 TOKEN_PRICE_PER_1K 估算"},
                },
            },
            "FeedbackRequest": {
                "type": "object", "required": ["trace_id"],
                "properties": {
                    "trace_id": {"type": "string"},
                    "useful": {"type": "boolean"},
                    "comment": {"type": "string", "maxLength": 500},
                    "behavior": {"type": "string"},
                    "query": {"type": "string"},
                    "expected": {"type": "string", "description": "本应怎么回答"},
                    "document": {"type": "string", "description": "缺哪份文档"},
                    "session_id": {"type": "string"},
                    "kb_version": {"type": "string"},
                },
            },
            "Error": {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                    "message": {"type": "string"},
                    "request_id": {"type": "string"},
                },
            },
        },
    }


def build_spec(version: str, auth: dict, model: str, retrieval: str) -> dict:
    secured = [{"bearerAuth": []}, {"apiKeyAuth": []}] if auth.get("mode") == "key" else []
    spec = {
        "openapi": "3.0.3",
        "info": _info(version, secured),
        "servers": [{"url": "/", "description": "当前实例"}],
        "tags": _tags(),
        "paths": {**_paths_qa(secured), **_paths_ops(), **_paths_kb(),
                  **_paths_admin(), **_paths_data(), **_paths_client(),
                  **_paths_meta()},
        "components": _components(),
    }
    spec["paths"].update(notes_paths())

    # 让文档里能看到当前实例的检索配置，避免「按默认阈值写死」的误用
    spec["info"]["x-retrieval"] = retrieval
    spec["info"]["x-model"] = model
    return spec
