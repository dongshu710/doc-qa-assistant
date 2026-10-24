"""给智能体用的工具声明（OpenAI function calling 风格）。

任何一个支持 function calling 的智能体，把 `tools` 数组塞进请求即可，
不需要读我们的文档；描述里写的是「什么时候该调用」，而不是接口用法。
"""

from __future__ import annotations

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "save_conversation",
            "description": ("把当前对话里值得长期保留的片段整理成一篇个人笔记并保存到用户的存储空间。"
                            "当用户说「记一下 / 存下来 / 整理成笔记 / 别丢了」或明确指明某几轮结论时使用；"
                            "不要每轮都调用，也不要保存寒暄。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "messages": {
                        "type": "array",
                        "description": "要保存的消息，按时间顺序。只放选中的片段，不要把整段对话都塞进来。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string", "enum": ["user", "assistant", "system", "tool"]},
                                "text": {"type": "string", "description": "消息正文"},
                            },
                            "required": ["role", "text"],
                            "additionalProperties": False,
                        },
                        "maxItems": 200,
                    },
                    "select": {
                        "type": "object",
                        "description": "可选：进一步筛选要保存哪几条，默认全部",
                        "properties": {
                            "mode": {"type": "string", "enum": ["all", "indices", "range", "keyword"]},
                            "indices": {"type": "array", "items": {"type": "integer", "minimum": 1}},
                            "start": {"type": "integer", "minimum": 1},
                            "end": {"type": "integer", "minimum": 1},
                            "keyword": {"type": "string"},
                            "max_chars": {"type": "integer", "minimum": 200, "maximum": 200000},
                        },
                        "additionalProperties": False,
                    },
                    "hint": {
                        "type": "object",
                        "description": "可选：标题、类型、标签。标题不传会取首条用户消息。",
                        "properties": {
                            "title": {"type": "string", "maxLength": 120},
                            "kind": {"type": "string", "enum": ["decision", "howto", "reference", "qa", "log"]},
                            "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                            "status": {"type": "string", "enum": ["draft", "final", "archived"]},
                        },
                        "additionalProperties": False,
                    },
                    "source": {
                        "type": "object",
                        "description": "可选：标注来源，便于以后追溯",
                        "properties": {
                            "agent": {"type": "string"},
                            "model": {"type": "string"},
                            "session": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                    "keep_raw": {"type": "boolean", "description": "是否把对话原文一并存进「原文」段，默认否"},
                    "commit": {"type": "boolean",
                               "description": "false 表示只预览不落盘；用户还在犹豫时先用 false 给他看"},
                },
                "required": ["messages"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": ("在用户已保存的笔记里按标签、类型或日期筛选。"
                            "当用户问「上次那个结论在哪 / 我之前存过什么」时先用它定位，不要凭空回忆。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "tag": {"type": "array", "items": {"type": "string"},
                            "description": "标签，多个标签取交集"},
                    "kind": {"type": "string", "enum": ["decision", "howto", "reference", "qa", "log"]},
                    "status": {"type": "string", "enum": ["draft", "final", "archived"]},
                    "since": {"type": "string", "description": "起始日期，格式 YYYY-MM-DD"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_note",
            "description": "按 id 读取一篇笔记的全文或某一节。搜索结果里拿到 id 后再调用它。",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "笔记 id，例如 20261024-205142-5fc510"},
                    "section": {"type": "string",
                                "description": "只要某一节：摘要 / 要点 / 决策 / 待办 / 原文 / 引用"},
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_note",
            "description": ("修改已保存笔记的标题、标签、状态或某几节内容。"
                            "修改前必须先 get_note 拿到 rev 并原样回传，否则会被拒绝（防止覆盖用户的手改）。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "base_rev": {"type": "string", "description": "get_note 返回的 rev"},
                    "title": {"type": "string", "maxLength": 120},
                    "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                    "kind": {"type": "string", "enum": ["decision", "howto", "reference", "qa", "log"]},
                    "status": {"type": "string", "enum": ["draft", "final", "archived"]},
                    "sections": {
                        "type": "object",
                        "description": "要改的小节，形如 {\"待办\": \"- [ ] …\"}；传空字符串表示删除该节",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["id", "base_rev"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_note",
            "description": ("把一篇笔记移入回收站。只有在用户明确说「删掉这篇」时使用；"
                            "不确定就先问。删除可恢复，但仍需确认。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "confirm": {"type": "boolean", "description": "必须为 true，表示用户已确认删除"},
                },
                "required": ["id", "confirm"],
                "additionalProperties": False,
            },
        },
    },
]


def tools_payload(version: str, base_url: str = "") -> dict:
    return {
        "schema": "tools/v1",
        "version": version,
        "base_url": base_url or "",
        "endpoints": {
            "save": "POST /api/notes",
            "search": "GET /api/notes?tag=&kind=&since=&limit=",
            "get": "GET /api/notes/{id}",
            "update": "PATCH /api/notes/{id}",
            "delete": "DELETE /api/notes/{id}?confirm=1",
        },
        "auth": "若服务端配置了 API_KEYS，需要 Authorization: Bearer <key> 或 X-API-Key",
        "tools": TOOLS,
    }
