"""HTTP 层共用的小工具与上限常量。

为什么单独一层：这些函数被路由模块和组合根同时用到；放在 server.py 里会造成循环导入。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from .. import jsonl
from ..paths import DOC_EXTS, PROJECT_ROOT, require_safe_name

def _open_folder(folder: str) -> None:
    """用系统文件管理器打开目录。三个平台各一条命令，失败抛 OSError 让调用方回结构化错误。"""
    if os.name == "nt":
        os.startfile(folder)  # noqa: S606 —— 打开的是用户自己的存储区
    elif sys.platform == "darwin":
        subprocess.Popen(["open", folder])
    else:
        subprocess.Popen(["xdg-open", folder])


MAX_BODY_BYTES = 8192
# 问答另给一档：上限 500 字的问题按 UTF-8 最多 1.5 KB，但用户会粘一大段再被
# MAX_INPUT_CHARS 拦下来。请求体上限卡在 8 KB 时，同样的「问题太长」在 501 字
# 走的是「请精简后重试」，在 3000 字走的是「body empty or too large」——
# 同一件事两种说法。放大到 64 KB，让超长问题统一走「问题过长」那条路。
ASK_MAX_BYTES = 64 * 1024
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
# 常量名保留：read/write 用它拼错误提示与 os.listdir 过滤，改名字只会多一轮机械替换。
ALLOWED_EXT = DOC_EXTS


def _knowledge_dir() -> str:
    return os.path.join(str(PROJECT_ROOT), "data", "knowledge")


def _raw_dir() -> str:
    """上传原文的落点。

    允许用 `RAW_DIR` 覆盖，不是为灵活性，是为**测试隔离**：端到端验证必然要
    真的上传文件，落点写死就会在仓库里留下二进制文件——真实踩过，验证表格
    格式时上传的 xlsx 被 `git add -A` 一起带进了提交。默认仍放在 `data/raw`。
    """
    configured = (os.environ.get("RAW_DIR") or "").strip()
    if configured:
        path = os.path.abspath(os.path.expanduser(configured))
    else:
        path = os.path.join(str(PROJECT_ROOT), "data", "raw")
    os.makedirs(path, exist_ok=True)
    return path


def _read_jsonl(path: str, limit: int) -> list[dict]:
    """尾部 N 条（旧 → 新）；调用方按需 reverse。"""
    return jsonl.tail_json(path, max(1, int(limit)))


def int_qs(qs: dict, key: str, default: int, low: int, high: int) -> int:
    """URL 里的整数参数：坏值一律回落默认值，并夹在区间内。

    不直接 `int(...)`：`?limit=abc` 抛的 ValueError 会一路穿出 do_GET，
    客户端拿到的是连接重置——没有状态码、没有响应体，项目里最难查的一类故障。
    实测 `/api/threads?limit=abc` 就是这样：服务端打了 traceback，
    客户端只看到 RemoteDisconnected。

    放在 common 而不是留在 read.py：写入侧（resources.py 的会话列表）也要用，
    各写一份迟早只修好其中一处。
    """
    try:
        value = int((qs.get(key) or [""])[0])
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


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
        # home 是「当前生效的存储区」原始值，与 home_effective 是同一个东西的两种叫法；
        # 原来只洗了后两个，把最直接的绝对路径漏了。
        for key in ("home", "home_effective", "home_default"):
            if notes.get(key):
                notes[key] = redact_path(notes[key])
    for key in ("config_path", "config_backup"):
        if out.get(key):
            out[key] = redact_path(out[key])
    # 首启引导（`/api/settings/setup`）与 MCP 面板把 home / default_home / target
    # 放在顶层，不在 notes 下面。原来只洗了 notes.* 与 config_*，这三个漏了——
    # 实测无 Key 请求 `/api/settings/mcp` 能拿到解释器绝对路径与家目录。
    for key in ("home", "default_home", "target"):
        if isinstance(out.get(key), str) and _looks_absolute(out[key]):
            out[key] = redact_path(out[key])
    # 同一份客户端清单在两个接口里叫两个名字（`mcp_targets` / `targets`），
    # 只洗一个的话，另一个仍会给出 `C:\Users\<用户名>\AppData\Roaming\...`。
    for key in ("mcp_targets", "targets"):
        for target in out.get(key) or []:
            if isinstance(target, dict) and target.get("path"):
                target["path"] = redact_path(target["path"])
    storage = out.get("storage")
    if isinstance(storage, dict):
        for item in storage.values():
            if isinstance(item, dict) and item.get("path"):
                item["path"] = redact_path(item["path"])
    # MCP 配置在两处形状不同：`/api/settings` 放在 mcp.config 下，
    # `/api/settings/mcp` 直接放在顶层 config 下。只洗前者时，实测
    # 后者仍会吐出解释器绝对路径、PYTHONPATH 与 NOTE_HOME。
    configs = []
    if isinstance(out.get("config"), dict):
        configs.append(out["config"])
    mcp_block = out.get("mcp")
    if isinstance(mcp_block, dict) and isinstance(mcp_block.get("config"), dict):
        configs.append(mcp_block["config"])
    for cfg in configs:
        servers = (cfg or {}).get("mcpServers") or {}
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


