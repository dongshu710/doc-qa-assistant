"""OpenAPI 3.0 描述：对外集成只需要这一份机器可读契约。

手写而不是从路由自动生成：路由是 `if/elif` 字符串分发，自动生成要么引入
框架依赖，要么写一套脆弱的反射；接口数量有限，手写反而更准。改动接口时
同步改这里，`tests/test_openapi.py` 会校验路径与关键字段不漂移。
"""
from __future__ import annotations

from .notes.contract import notes_paths


def _err(desc: str) -> dict:
    return {"description": desc,
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}


def build_spec(version: str, auth: dict, model: str, retrieval: str) -> dict:
    secured = [{"bearerAuth": []}, {"apiKeyAuth": []}] if auth.get("mode") == "key" else []

    def security():
        return {"security": secured} if secured else {}

    spec = {
        "openapi": "3.0.3",
        "info": {
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
        },
        "servers": [{"url": "/", "description": "当前实例"}],
        "tags": [
            {"name": "问答", "description": "检索、生成与反馈"},
            {"name": "知识库", "description": "文档、版本与审批"},
            {"name": "笔记", "description": "对话整理成个人笔记：保存、查询、修改、删除"},
            {"name": "运维", "description": "健康检查与指标"},
        ],
        "paths": {
            "/api/ask": {
                "post": {
                    "tags": ["问答"], "summary": "提问（一次性返回）",
                    "operationId": "ask",
                    **security(),
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
                    **security(),
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
            "/api/health": {
                "get": {
                    "tags": ["运维"], "summary": "健康检查",
                    "responses": {"200": {"description": "服务、索引、知识库与防护状态",
                                          "content": {"application/json": {
                                              "schema": {"type": "object"}}}}},
                }
            },
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
            "/api/knowledge/delete": {
                "post": {"tags": ["知识库"], "summary": "删除文档",
                         "requestBody": {"required": True, "content": {"application/json": {
                             "schema": {"type": "object", "required": ["name"], "properties": {
                                 "name": {"type": "string"}}}}}},
                         "responses": {"200": {"description": "已删除"},
                                       "404": _err("文件不存在")}}
            },
            "/api/reload": {
                "post": {"tags": ["运维"], "summary": "重建索引（默认后台执行）",
                         "responses": {"200": {"description": "rebuilding=true 表示已排队"}}}
            },
            "/api/metrics": {
                "get": {"tags": ["运维"], "summary": "业务聚合指标",
                        "responses": {"200": {"description": "请求量、延迟、降级与 token"}}}
            },
        },
        "components": {
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
                        "chunk_index": {"type": "integer"},
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
        },
    }
    spec["paths"].update(notes_paths())

    # 让文档里能看到当前实例的检索配置，避免「按默认阈值写死」的误用
    spec["info"]["x-retrieval"] = retrieval
    spec["info"]["x-model"] = model
    return spec
