"""HTTP 层共用的小工具与上限常量。

为什么单独一层：这些函数被路由模块和组合根同时用到；放在 server.py 里会造成循环导入。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from .. import ingest, jsonl

def _open_folder(folder: str) -> None:
    """用系统文件管理器打开目录。三个平台各一条命令，失败抛 OSError 让调用方回结构化错误。"""
    if os.name == "nt":
        os.startfile(folder)  # noqa: S606 —— 打开的是用户自己的存储区
    elif sys.platform == "darwin":
        subprocess.Popen(["open", folder])
    else:
        subprocess.Popen(["xdg-open", folder])


MAX_BODY_BYTES = 8192
NOTES_MAX_BYTES = 2 * 1024 * 1024        # 一段对话可能很长：笔记接口单独放宽
UPLOAD_MAX_BYTES = 512 * 1024          # 单个文本文件上限（.md/.txt）
DOC_MAX_BYTES = 6 * 1024 * 1024         # 单个 PDF/DOCX 上限（解码后）
DOC_B64_MAX_BYTES = DOC_MAX_BYTES * 4 // 3 + 4096
# 附件的原始上限是 8 MB（`notes/assets.py` 的 MAX_BYTES），走 base64 后膨胀 4/3，
# 再留一点 JSON 包装的余量。请求体上限必须比它大，否则合法附件会在读取阶段就被拒。
ASSET_MAX_BYTES = 8 * 1024 * 1024
ASSET_BODY_MAX = ASSET_MAX_BYTES * 4 // 3 + 64 * 1024
SSE_HEARTBEAT_S = 15.0                  # 流式回答的空闲心跳间隔
SSE_MAX_SECONDS = 300.0                 # 单次流式回答的总时长上限
ALLOWED_EXT = (".md", ".txt")


def _safe_kb_name(name) -> str | None:
    """只接受「纯文件名」的 .md/.txt。

    显式拒绝路径分隔符而不是 basename 静默改名：
    静默改名虽然安全，但会让用户以为传了 `../x.md` 却出现 `x.md`，属于隐性行为。
    """
    raw = str(name or "").strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw:
        return None
    if len(raw) > 80 or not raw.lower().endswith(ALLOWED_EXT):
        return None
    if any(ch in raw for ch in '<>:"|?*\x00'):
        return None
    return raw


def _knowledge_dir() -> str:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "data", "knowledge")


def _raw_dir() -> str:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, "data", "raw")
    os.makedirs(path, exist_ok=True)
    return path


def _safe_doc_name(name) -> str | None:
    """上传文档名：只接受纯文件名，且扩展名必须在 `ingest.SUPPORTED_EXT` 内。"""
    raw = str(name or "").strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw:
        return None
    if len(raw) > 120 or not raw.lower().endswith(ingest.SUPPORTED_EXT):
        return None
    if any(ch in raw for ch in '<>:"|?*\x00'):
        return None
    return raw


def _read_jsonl(path: str, limit: int) -> list[dict]:
    """尾部 N 条（旧 → 新）；调用方按需 reverse。"""
    return jsonl.tail_json(path, max(1, int(limit)))


def redact_path(value) -> str:
    """把绝对路径压成 `…/末级`，只保留「指的是哪个目录」。

    路径本身不是密钥，但它暴露用户名与目录结构。`/api/settings` 是开放接口
    （Key 配错时的回退通道），对外部署时没必要顺手把家目录也交出去。
    """
    text = str(value or "")
    if not text:
        return ""
    parts = [seg for seg in text.replace("\\", "/").split("/") if seg and seg != "."]
    if len(parts) <= 1:
        return text
    return "…/" + parts[-1]


def _looks_absolute(value: str) -> bool:
    return os.path.isabs(value) or (len(value) > 1 and value[1] == ":")


def redact_settings(payload: dict) -> dict:
    """配了 API_KEYS 又没带有效 Key 时，把设置回包里的绝对路径收起来。

    深拷贝一份再改：`_settings_payload()` 的结果会同时被审计写入用到，
    原地改会让同一份数据两处不一致。
    """
    out = json.loads(json.dumps(payload, ensure_ascii=False))
    notes = out.get("notes")
    if isinstance(notes, dict):
        for key in ("home_effective", "home_default"):
            if notes.get(key):
                notes[key] = redact_path(notes[key])
    for key in ("config_path", "config_backup"):
        if out.get(key):
            out[key] = redact_path(out[key])
    for target in out.get("mcp_targets") or []:
        if isinstance(target, dict) and target.get("path"):
            target["path"] = redact_path(target["path"])
    storage = out.get("storage")
    if isinstance(storage, dict):
        for item in storage.values():
            if isinstance(item, dict) and item.get("path"):
                item["path"] = redact_path(item["path"])
    servers = ((out.get("mcp") or {}).get("config") or {}).get("mcpServers") or {}
    for server in servers.values():
        if not isinstance(server, dict):
            continue
        if isinstance(server.get("command"), str) and _looks_absolute(server["command"]):
            server["command"] = redact_path(server["command"])
        for key, value in list((server.get("env") or {}).items()):
            if isinstance(value, str) and _looks_absolute(value):
                server["env"][key] = redact_path(value)
    out["redacted"] = True
    return out


