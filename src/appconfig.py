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
import shutil
import tempfile
import threading
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
# 手改配置写坏了不能装作没发生：界面上要能看见「现在显示的是默认值」，
# 否则用户以为密钥丢了，其实是 JSON 少了一个逗号（反过来更糟：再点一次保存就把原文盖掉）。
_parse_error = ""
_last_backup = ""
# 每次写盘 +1，给 config 的 1 秒缓存做精确失效；光靠 TTL 会让「保存后立刻生效」出现 1 秒空窗。
_revision = 0
# 配置是整文件读改写：导出（记时间）与保存设置同时发生时会互相覆盖，用进程内锁串起来。
# 跨进程只有 CLI/MCP 读配置、不写，所以一把本地锁足够。
_write_lock = threading.Lock()


def revision() -> int:
    return _revision


def path() -> Path:
    override = os.environ.get("APP_CONFIG", "").strip()
    return Path(override).expanduser() if override else DEFAULT_PATH


_TRUE = {"1", "true", "on", "yes", "y", "是", "开"}
_FALSE = {"0", "false", "off", "no", "n", "否", "关"}


def _as_bool(value, *, strict: bool = False) -> bool:
    """把 JSON / 表单里的值折成布尔。

    不能直接 bool("false")——那是 True，会让「储存对话内容」在用户明确写 false 时反而打开。
    读路径遇到无法识别的值一律按 False（少存优于多存）；写路径直接报错，别猜。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
    if strict:
        raise ValueError("开关只能填 true / false（也接受 on / off）")
    return False


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


def _decode(raw: bytes) -> str:
    """按 UTF-8 → GBK 依次试。

    中文 Windows 的记事本默认「ANSI」就是 GBK：用户手改一次配置，服务就直接起不来
    （`UnicodeDecodeError` 不在原来的 OSError 分支里）。写入统一用 UTF-8，读的时候宽容一点。
    """
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", raw, 0, min(1, len(raw)), "既不是 UTF-8 也不是 GBK")


def _read() -> dict:
    global _cache, _cache_stat, _parse_error
    target = path()
    try:
        stat = target.stat()
    except OSError:
        _cache, _cache_stat, _parse_error = {}, None, ""
        return {}
    # 按 mtime + size 失效：用户手改 app.json 也能立刻生效，不必重启服务
    stamp = (stat.st_mtime, stat.st_size)
    if _cache is not None and _cache_stat == stamp:
        return _cache
    try:
        data = json.loads(_decode(target.read_bytes()))
        if not isinstance(data, dict):
            data, _parse_error = {}, "顶层必须是一个 JSON 对象"
        else:
            _parse_error = ""
    except json.JSONDecodeError as exc:
        # 坏文件不能让整个服务起不来：当作没配过，但要把「哪里坏了」留给界面
        data = {}
        _parse_error = f"第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}"
    except UnicodeDecodeError:
        data = {}
        _parse_error = "文件编码无法识别（既不是 UTF-8 也不是 GBK）"
    except OSError as exc:
        data = {}
        _parse_error = f"读取失败：{exc}"
    _cache, _cache_stat = data, stamp
    return data


def _backup_broken(target: Path) -> str:
    """写之前若原文件不是合法 JSON，先留一份原件。

    这条路径防的是「手改少个逗号 → 界面显示成默认值 → 点一次保存 → 密钥被覆盖没了」。
    备份失败不阻断保存，但要返回空串，界面就不会谎称已备份。
    """
    if not target.exists():
        return ""
    try:
        text = _decode(target.read_bytes())
    except OSError:
        return ""
    except UnicodeDecodeError:
        text = None          # 编码都认不出，同样是「坏文件」，必须备份
    if text is not None:
        try:
            json.loads(text)
            return ""
        except json.JSONDecodeError:
            pass
    backup = target.with_name(f"{target.name}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    try:
        shutil.copy2(target, backup)
    except OSError:
        return ""
    return str(backup)


def _write(data: dict) -> None:
    """原子写：先落临时文件再替换，避免半个 JSON 把配置彻底读废。"""
    global _parse_error, _last_backup, _revision
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    _last_backup = _backup_broken(target)
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
    _parse_error = ""
    _revision += 1


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
            out[meta["env"]] = "on" if _as_bool(value) else "off"
        else:
            out[meta["env"]] = str(value)
    return out


def store_chat() -> bool:
    value = _dig(_read(), "notes.store_chat")
    if value is None:
        # 配置里没写过就认环境变量：SCHEMA 与 .env.example 都声明了 STORE_CHAT，
        # 只读配置文件会让这个开关「写了不生效」，比没有更误导。
        return _as_bool(os.environ.get("STORE_CHAT", ""))
    return _as_bool(value)


BACKUP_STALE_DAYS = 30


def mark_exported() -> None:
    """记一次成功导出。

    备份提醒只认这个时间，不去猜用户有没有手动拷走目录——
    「看起来备份过」和「真的导出过」是两件事，猜错会让人以为有保障。
    """
    global _cache, _cache_stat
    with _write_lock:
        # 整文件读改写：不加锁会和「保存设置」互相覆盖（导出记一次时间，把刚填的密钥盖回旧值）
        data = json.loads(json.dumps(_read()))
        stamp = datetime.now(timezone.utc).isoformat()
        _put(data, "notes.last_export_at", stamp)
        data["updated_at"] = stamp
        _write(data)
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
    if when.tzinfo is None:
        # 手改配置常写成「2026-10-01T10:00:00」这种不带时区的形式。
        # 直接和 UTC 相减会抛 TypeError，把整个设置面板打成 500——按本机时区补齐即可。
        when = when.astimezone()
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
        # 不能固定叫 .write-test：万一目录里真有同名文件，测一次写权限就把人家删了
        handle, probe = tempfile.mkstemp(dir=str(target), prefix=".write-test-")
        os.close(handle)
        os.unlink(probe)
    except OSError as exc:
        raise ValueError(f"这个位置不可写：{exc}") from exc
    return str(target)


def update(patch: dict) -> dict:
    """合并写入。只接受 SCHEMA 里的键，其余静默丢弃，防止手滑写坏文件。"""
    if not isinstance(patch, dict):
        raise ValueError("请求体必须是 JSON 对象")
    llm = patch.get("llm") or {}
    notes = patch.get("notes") or {}

    global _cache, _cache_stat
    with _write_lock:
        data = json.loads(json.dumps(_read()))  # 深拷贝，失败时不污染缓存

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
            incoming["notes.store_chat"] = _as_bool(notes["store_chat"], strict=True)

        for dotted, value in incoming.items():
            _put(data, dotted, value)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write(data)
        _cache, _cache_stat = None, None    # 下次读重新加载，保证本进程立刻看到新值
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
            # 走 store_chat() 而不是直接读文件：界面显示的必须是「实际生效值」，
            # 否则 STORE_CHAT=on 时开关显示为关，而保存却被放行，自相矛盾
            "store_chat": store_chat(),
        },
        "config_path": str(path()),
        "config_error": _parse_error,
        "config_backup": _last_backup,
        "updated_at": data.get("updated_at") or "",
    }
