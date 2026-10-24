"""笔记接口的 OpenAPI 片段。

单独成文件而不是塞进 openapi.py：那支文件已经很长，而这里的结构是
「一屏能看完」的，放在一起容易数错括号（上一版就栽在这儿）。
"""

from __future__ import annotations

ERROR_REF = {"$ref": "#/components/schemas/Error"}
NOTE_REF = {"$ref": "#/components/schemas/Note"}
KINDS = ["decision", "howto", "reference", "qa", "log"]
STATUSES = ["draft", "final", "archived"]

MESSAGE_ITEM = {
    "type": "object",
    "required": ["role", "text"],
    "properties": {
        "role": {"type": "string", "enum": ["user", "assistant", "system", "tool"]},
        "text": {"type": "string"},
    },
}

SAVE_SCHEMA = {
    "type": "object",
    "required": ["messages"],
    "properties": {
        "messages": {"type": "array", "items": MESSAGE_ITEM, "maxItems": 200},
        "select": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["all", "indices", "range", "keyword"]},
                "indices": {"type": "array", "items": {"type": "integer", "minimum": 1}},
                "start": {"type": "integer", "minimum": 1},
                "end": {"type": "integer", "minimum": 1},
                "keyword": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 200, "maximum": 200000},
            },
        },
        "hint": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "maxLength": 120},
                "kind": {"type": "string", "enum": KINDS},
                "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                "status": {"type": "string", "enum": STATUSES},
            },
        },
        "source": {
            "type": "object",
            "properties": {
                "agent": {"type": "string"},
                "model": {"type": "string"},
                "session": {"type": "string"},
            },
        },
        "keep_raw": {"type": "boolean", "default": False,
                     "description": "是否把对话原文写进「原文」段"},
        "digest": {"type": "string", "enum": ["rule", "auto", "llm"], "default": "rule",
                   "description": "摘要引擎；auto/llm 失败会回落 rule 并记 digest_fallback"},
        "commit": {"type": "boolean", "default": True,
                   "description": "false = 只预览不落盘"},
    },
}

PATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "base_rev": {"type": "string", "description": "GET 返回的 rev；不传会被拒绝（除非 force）"},
        "force": {"type": "boolean", "default": False},
        "changes": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "maxLength": 120},
                "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                "kind": {"type": "string", "enum": KINDS},
                "status": {"type": "string", "enum": STATUSES},
                "sections": {"type": "object", "additionalProperties": {"type": "string"}},
            },
        },
    },
}


def _body(schema: dict) -> dict:
    return {"required": True, "content": {"application/json": {"schema": schema}}}


def _err_response(desc: str) -> dict:
    return {"description": desc, "content": {"application/json": {"schema": ERROR_REF}}}


def notes_paths() -> dict:
    return {
        "/api/notes": {
            "get": {
                "tags": ["笔记"],
                "summary": "列出笔记",
                "parameters": [
                    {"name": "tag", "in": "query", "style": "form", "explode": True,
                     "schema": {"type": "array", "items": {"type": "string"}},
                     "description": "标签，可重复，取交集"},
                    {"name": "kind", "in": "query", "schema": {"type": "string", "enum": KINDS}},
                    {"name": "status", "in": "query", "schema": {"type": "string", "enum": STATUSES}},
                    {"name": "since", "in": "query", "schema": {"type": "string"},
                     "description": "起始日期 YYYY-MM-DD"},
                    {"name": "limit", "in": "query",
                     "schema": {"type": "integer", "minimum": 0, "maximum": 200, "default": 20}},
                ],
                "responses": {
                    "200": {
                        "description": "笔记列表",
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "properties": {
                                "ok": {"type": "boolean"},
                                "count": {"type": "integer"},
                                "items": {"type": "array", "items": NOTE_REF},
                            },
                        }}},
                    },
                },
            },
            "post": {
                "tags": ["笔记"],
                "summary": "把一段对话整理成笔记（commit=false 只预览）",
                "requestBody": _body(SAVE_SCHEMA),
                "responses": {
                    "201": {"description": "已保存"},
                    "200": {"description": "预览，或内容已存在（看 duplicate_of）"},
                    "400": _err_response("参数不合法"),
                },
            },
        },
        "/api/notes/{id}": {
            "get": {
                "tags": ["笔记"],
                "summary": "读取一篇笔记（可只取某一节）",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                    {"name": "section", "in": "query", "schema": {"type": "string"},
                     "description": "摘要 / 要点 / 决策 / 待办 / 原文 / 引用"},
                ],
                "responses": {
                    "200": {"description": "笔记正文，含 rev（PATCH 要用）"},
                    "404": _err_response("笔记不存在"),
                },
            },
            "patch": {
                "tags": ["笔记"],
                "summary": "局部修改（默认需 base_rev 乐观锁）",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                ],
                "requestBody": _body(PATCH_SCHEMA),
                "responses": {
                    "200": {"description": "修改后的笔记"},
                    "400": _err_response("参数不合法或缺少 base_rev"),
                    "409": _err_response("rev 冲突：请重新 GET 再改"),
                },
            },
            "delete": {
                "tags": ["笔记"],
                "summary": "移入回收站（需确认）",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                    {"name": "confirm", "in": "query", "schema": {"type": "boolean"},
                     "description": "必须为 true，或请求体 {\"confirm\": true}"},
                ],
                "responses": {
                    "200": {"description": "已移入 .trash，可找回"},
                    "400": _err_response("缺少确认"),
                    "404": _err_response("笔记不存在"),
                },
            },
        },
        "/api/notes/stats": {
            "get": {
                "tags": ["笔记"],
                "summary": "数量与标签分布",
                "responses": {"200": {"description": "统计结果"}},
            },
        },
    }
