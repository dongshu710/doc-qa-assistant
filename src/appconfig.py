"""运行时配置：界面里改的东西落在这里，立刻生效，不用重启、不用改环境变量。

优先级：显式参数 > 界面配置（`data/app.json`）> 环境变量 > 代码默认。
界面排在环境变量前面，是因为用户在页面上点过之后，改不动比没有开关更糟。

为什么单独一个文件而不是直接改 os.environ：环境变量是进程级全局状态，
写进去就再也分不清「用户配的」和「启动时带的」，也没法在页面上回显与撤销。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "app.json"

# 只开放真正需要用户选的项；其余参数仍走环境变量，避免设置面板变成参数垃圾场
SCHEMA = {
    "llm.base_url": {"env": "LLM_BASE_URL", "type": "str", "required": True},
    "llm.model": {"env": "LLM_MODEL", "type": "str", "required": True},
    "llm.api_key": {"env": "LLM_API_KEY", "type": "str", "required": False},
    "notes.home": {"env": "NOTE_HOME", "type": "path", "required": False},
    "notes.store_chat": {"env": "STORE_CHAT", "type": "bool", "required": False},
}

DEFAULTS = {
    "llm.base_url": "https://api.deepseek.com/v1",
    "llm.model": "deepseek-chat",
    "llm.api_key": "",
    "notes.home": "",
    "notes.store_chat": False,
}

_cache: dict | None = None
_cache_stat: tuple[float, int] | None = None


def path() -> Path:
    override = os.environ.get("APP_CONFIG", "").strip()
    return Path(override).expanduser() if override else DEFAULT_PATH


def _dig(data: dict, dotted: str):
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _put(data: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _read() -> dict:
    global _cache, _cache_stat
    target = path()
    try:
        stat = target.stat()
    except OSError:
        _cache, _cache_stat = {}, None
        return {}
    # 按 mtime + size 失效：用户手改 app.json 也能立刻生效，不必重启服务
    stamp = (stat.st_mtime, stat.st_size)
    if _cache is not None and _cache_stat == stamp:
        return _cache
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        # 坏文件不能让整个服务起不来：当作没配过，界面上会显示默认值
        data = {}
    _cache, _cache_stat = data, stamp
    return data


def _write(data: dict) -> None:
    """原子写：先落临时文件再替换，避免半个 JSON 把配置彻底读废。"""
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    handle, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".app-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get(dotted: str, default=None):
    """取单项；没配过返回 default（而不是环境变量，环境变量由调用方自己兜）。"""
    value = _dig(_read(), dotted)
    return default if value in (None, "") else value


def as_env() -> dict[str, str]:
    """映射成环境变量名 → 值，供 config._first_env 覆盖使用。"""
    out: dict[str, str] = {}
    data = _read()
    for dotted, meta in SCHEMA.items():
        value = _dig(data, dotted)
        if value is None:
            continue        # 没写过这一项：交给环境变量兜底
        # 写过就照实输出，哪怕空串。空串是「用户主动清空」，不能再被环境变量顶回来
        if meta["type"] == "bool":
            out[meta["env"]] = "on" if value else "off"
        else:
            out[meta["env"]] = str(value)
    return out


def store_chat() -> bool:
    value = _dig(_read(), "notes.store_chat")
    if value is None:
        return False
    return bool(value)


BACKUP_STALE_DAYS = 30


def mark_exported() -> None:
    """记一次成功导出。

    备份提醒只认这个时间，不去猜用户有没有手动拷走目录——
    「看起来备份过」和「真的导出过」是两件事，猜错会让人以为有保障。
    """
    data = json.loads(json.dumps(_read()))
    _put(data, "notes.last_export_at", datetime.now(timezone.utc).isoformat())
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write(data)
    global _cache, _cache_stat
    _cache, _cache_stat = None, None


def last_export_at() -> str:
    return str(_dig(_read(), "notes.last_export_at") or "")


def backup_state(notes_count: int) -> dict:
    """是否该提醒备份。没笔记就不提醒——空库提示备份只会制造噪音。"""
    raw = last_export_at()
    if notes_count <= 0:
        return {"due": False, "last_export_at": raw, "days": None, "text": ""}
    if not raw:
        return {"due": True, "last_export_at": "", "days": None, "text": "还没备份过"}
    try:
        when = datetime.fromisoformat(raw)
    except ValueError:
        return {"due": True, "last_export_at": raw, "days": None, "text": "备份时间无法识别"}
    days = max(0, (datetime.now(timezone.utc) - when).days)
    if days == 0:
        text = "今天备份过"
    elif days == 1:
        text = "昨天备份过"
    else:
        text = f"上次备份 {days} 天前"
    return {"due": days >= BACKUP_STALE_DAYS, "last_export_at": raw,
            "days": days, "text": text}


def _check_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not re.match(r"^https?://[^\s/]+", value):
        raise ValueError("接口地址要写成 https://… 的形式")
    return value


def clean_path(raw: str) -> str:
    """清洗粘贴来的路径：去空白、去包裹的引号、展开 ~。

    从资源管理器「复制为路径」拿到的字符串带双引号（"D:\\我的笔记"），
    直接丢给 Path 会当成文件名的一部分，报「不可写」——用户看不出哪里错了。
    """
    text = str(raw or "").strip()
    # 左右引号可能不是同一个字符（中文引号就是 “ 和 ”），得成对匹配
    for left, right in (('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’")):
        if len(text) >= 2 and text.startswith(left) and text.endswith(right):
            text = text[1:-1]
    return text.strip()


def _check_home(value: str) -> str:
    """自定义存储位置：必须是绝对路径，且真的能建目录、能写文件。

    只在界面点了应用时才调，不要求目录已存在——用户选一个新文件夹是常规操作。
    """
    raw = clean_path(value)
    if not raw:
        return ""
    target = Path(raw).expanduser()
    if not target.is_absolute():
        raise ValueError("存储位置要填绝对路径，例如 D:\\我的笔记")
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise ValueError(f"这个位置不可写：{exc}") from exc
    return str(target)


def update(patch: dict) -> dict:
    """合并写入。只接受 SCHEMA 里的键，其余静默丢弃，防止手滑写坏文件。"""
    if not isinstance(patch, dict):
        raise ValueError("请求体必须是 JSON 对象")
    data = json.loads(json.dumps(_read()))  # 深拷贝，失败时不污染缓存
    llm = patch.get("llm") or {}
    notes = patch.get("notes") or {}

    incoming: dict[str, object] = {}
    if "base_url" in llm:
        incoming["llm.base_url"] = _check_base_url(str(llm["base_url"]))
    if "model" in llm:
        model = str(llm["model"]).strip()
        if not model:
            raise ValueError("模型名不能为空")
        incoming["llm.model"] = model
    if "api_key" in llm:
        incoming["llm.api_key"] = str(llm["api_key"]).strip()
    if "home" in notes:
        incoming["notes.home"] = _check_home(str(notes["home"]))
    if "store_chat" in notes:
        incoming["notes.store_chat"] = bool(notes["store_chat"])

    for dotted, value in incoming.items():
        _put(data, dotted, value)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write(data)
    global _cache, _cache_stat
    _cache, _cache_stat = None, None        # 下次读重新加载，保证本进程立刻看到新值
    return view()


def mask(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:6]}{'*' * 6}{secret[-4:]}"


def view() -> dict:
    """给界面看的样子：密钥只回掩码，不回原文。

    页面不需要原文——改了才提交，没改就留空，服务端据此判断「保持不变」。
    """
    data = _read()
    base_url = _dig(data, "llm.base_url") or ""
    model = _dig(data, "llm.model") or ""
    key = _dig(data, "llm.api_key") or ""
    home = _dig(data, "notes.home") or ""
    return {
        "llm": {
            "base_url": base_url,
            "model": model,
            "api_key_masked": mask(key),
            "api_key_set": bool(key),
            "base_url_default": DEFAULTS["llm.base_url"],
            "model_default": DEFAULTS["llm.model"],
        },
        "notes": {
            "home": home,
            "store_chat": bool(_dig(data, "notes.store_chat")),
        },
        "config_path": str(path()),
        "updated_at": data.get("updated_at") or "",
    }
