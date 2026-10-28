"""HTTP 路由层：按职责拆分，组合根在 `app.py`。

    app.py        组装运行时依赖，把下面四个路由类拼成一个 Handler
    base.py       响应/压缩/ETag、来源闸门、鉴权、PUT/PATCH/DELETE/OPTIONS
    resources.py  笔记、会话、文件、存储、设置
    read.py       页面与只读 API
    write.py      问答（含 SSE）、知识库、设置写入、评测用例

路由总览（鉴权等级见 `src/routing.py`）：

    页面    GET  /ask /kb /files；/ /index.html /insights /dashboard /report → 302 /ask

    只读    GET  /api/health /openapi.json /metrics /api/metrics /api/examples /api/l3
                 /api/knowledge /api/keywords /api/kb/versions /api/kb/changes
                 /api/kb/change /api/kb/doc_history /api/source /api/feedback/list
                 /api/trace /api/audit /api/admin/config /api/admin/cost /api/cases
                 /api/notes[/{id}] /api/threads[/{id}] /api/files/raw
                 /api/storage/backups /api/settings

    写入    POST /api/ask /api/ask/stream /api/session/clear /api/feedback /api/reload
                 /api/keywords/rebuild /api/admin/config /api/admin/rollback
                 /api/kb/approve /api/kb/reject /api/kb/rollback_doc
                 /api/knowledge/upload /api/knowledge/upload_file /api/knowledge/upload_pdf
                 /api/knowledge/delete /api/cases/from_doc /api/cases/run
                 /api/storage/backup /api/storage/restore /api/settings/*
            PUT  /api/files/raw /api/threads/{id}
            PATCH  /api/notes/{id} /api/threads/{id}
            DELETE /api/notes/{id} /api/threads/{id}

新增接口的做法：在对应模块的 `do_*` 分支里挂上，并在 `src/routing.py` 登记等级。
未登记的 `/api/*` 默认按 `api` 处理（要 Key），所以漏登记是「更严格」，不是「裸奔」。
"""
