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


