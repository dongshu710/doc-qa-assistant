#!/usr/bin/env python3
"""从代码生成 `.env.example`，并在 CI 里校验它没有漂移。

为什么要有这个工具：环境变量散在 20 多个模块里读，靠人手维护一份示例文件，
结局一定是「文档里有的代码不认，代码认的文档里没有」。实测过一次：
`LLM_BACKOFF_BASE_S` 在 README 里出现，代码里只有 dataclass 默认值、从不读环境。

做法：以代码为准静态提取，而不是以人的记忆为准。
- `config.py` 里 `field=_first_env("ENV", default="x")` → 用户级配置，带默认值；
- 其它模块 `os.getenv("ENV")` / `_env_int(...)` → 进阶调参，标注来源文件；
- 敏感变量（KEY / TOKEN / 密码）一律输出空值，绝不把开发机上的真实值写进仓库。

用法：
    python tools/gen_env_example.py            # 生成或更新 .env.example
    python tools/gen_env_example.py --check    # 只校验，不一致则退出码 1（CI 用）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".env.example"

FIELD_ENV = re.compile(
    r'^\s{4,8}([a-z_0-9]+)\s*=\s*.*?_(?:first_env|env_int|env_float)\(\s*"([A-Z0-9_]+)"'
    r'(?:[^)]*?default=(?:"([^"]*)"|(\d+(?:\.\d+)?)))?',
    re.M)
ANY_ENV = re.compile(
    r'(?:os\.getenv|os\.environ\.get|_first_env|_env_int|_env_float|getenv|_env_flag)'
    r'\(\s*"([A-Z][A-Z0-9_]+)"')

SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD")

# 系统或启动方式给的变量，不是本项目的配置
SYSTEM_ENV = {"APP_CONFIG", "APPDATA", "USERNAME", "PATH", "PYTHONPATH", "HOME", "TEMP", "TMP"}

# 分组只影响阅读顺序，不影响行为。前缀判断从长到短，避免 NOTE_ 抢走 NOTE_SEARCH_。
GROUPS: list[tuple[str, str, str]] = [
    ("llm", "问答模型", "接哪家模型、怎么重试。改了要重启服务。"),
    ("embedding", "向量检索", "embedding 服务与索引。留空即用本地 hash 向量（零依赖，不联网）。"),
    ("vector", "向量索引后端", "auto 会优先 numpy/faiss，都没有就用纯 Python。"),
    ("retrieval", "检索与阈值", "召回条数、最低分。阈值调低会把无关段落当依据。"),
    ("keyword", "关键词直出", "命中关键词时直接给条款，不调模型。"),
    ("top_k", "检索与阈值", ""),
    ("min_score", "检索与阈值", ""),
    ("hedge", "检索与阈值", ""),
    ("rrf", "检索与阈值", ""),
    ("query_expansion", "检索与阈值", ""),
    ("chunk", "分块", "切多长的块、相邻块重叠多少。overlap 默认 auto。"),
    ("citation", "引用与拒答", "引用支持率不达标时是否降级。"),
    ("max_context", "上下文", ""),
    ("max_input", "上下文", ""),
    ("wall_clock", "上下文", ""),
    ("kb", "知识库", "版本审批、保留几个历史版本。"),
    ("admin", "鉴权", "管理员令牌。留空时仅本机可做管理操作。"),
    ("api_keys", "鉴权", "逗号分隔。非回环监听时必须设置，否则服务拒绝启动。"),
    ("allowed_hosts", "鉴权", "额外放行的 Host，逗号分隔。"),
    ("redis", "多实例（可选）", "不设则用进程内限流与计费；多实例部署才需要。"),
    ("rate_limit", "限流与成本", ""),
    ("daily_token", "限流与成本", ""),
    ("idempotency", "限流与成本", ""),
    ("token_price", "限流与成本", ""),
    ("canary", "灰度", "按百分比把流量分给另一个模型。"),
    ("note", "笔记", "存储区、检索预算、附件策略。"),
    ("notes", "笔记", ""),
    ("store_chat", "笔记", ""),
    ("setup", "首次引导", ""),
    ("settings", "界面", ""),
    ("log", "日志与审计", ""),
    ("debug", "日志与审计", ""),
    ("profile", "运行模式", ""),
    ("app", "运行模式", ""),
    ("probe", "内部工具", "设置面板的连通性探测，一般不用改。"),
    ("report", "内部工具", ""),
    ("pdf", "入库解析", ""),
    ("mcp", "MCP", ""),
    ("user", "系统环境", "由操作系统提供，不要自己设。"),
    ("appdata", "系统环境", ""),
]


def kind_of(name: str) -> tuple[str, str, str]:
    low = name.lower()
    for prefix, title, note in GROUPS:
        if low.startswith(prefix.lower()):
            return title, note, prefix
    return "其他", "", ""


def settings_entries() -> dict[str, dict]:
    """从 config.py 提取「字段 → 环境变量」，默认值尽量取运行时真值。

    为什么不用正则抓 `default="x"`：有些默认值是变量（`default=default_min`），
    抓不到就成了空，示例文件写着「空」而代码里其实有默认值，比不写更误导。
    运行时取值的方法是把已知变量全部临时摘掉再 load_settings()，读到的就是纯默认。
    """
    text = (ROOT / "src" / "config.py").read_text(encoding="utf-8")
    out: dict[str, dict] = {}
    pairs: list[tuple[str, str]] = []
    for match in FIELD_ENV.finditer(text):
        field, env, text_default, number_default = match.groups()
        default = text_default if text_default is not None else (number_default or "")
        pairs.append((field, env))
        out[env] = {"field": field, "default": default, "where": "src/config.py"}

    defaults = _runtime_defaults([field for field, _ in pairs])
    for field, env in pairs:
        if field in defaults:
            value = defaults[field]
            out[env]["default"] = "" if value is None else str(value)
    return out


def _runtime_defaults(fields: list[str]) -> dict[str, object]:
    """在「没有任何环境变量、没有界面配置」的条件下读一遍默认值。"""
    import os

    names = sorted({name for name, _ in [(n, None) for n in _all_env_names()]})
    saved = {name: os.environ.pop(name) for name in names if name in os.environ}
    saved_config = os.environ.get("APP_CONFIG")
    os.environ["APP_CONFIG"] = str(ROOT / ".gen-env-no-config.json")
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from src.config import load_settings  # noqa: PLC0415 —— 必须在这个 env 状态下导入
        settings = load_settings()
        return {field: getattr(settings, field, "") for field in fields}
    except Exception as exc:  # noqa: BLE001 —— 取不到就退回正则里的默认值
        print(f"提示：读取运行时默认值失败（{type(exc).__name__}: {exc}），改用源码里的字面量",
              file=sys.stderr)
        return {}
    finally:
        os.environ.update(saved)
        if saved_config is None:
            os.environ.pop("APP_CONFIG", None)
        else:
            os.environ["APP_CONFIG"] = saved_config


def _all_env_names() -> set[str]:
    text = "".join(path.read_text(encoding="utf-8")
                   for path in (ROOT / "src").rglob("*.py"))
    return set(ANY_ENV.findall(text))


def scattered_entries() -> dict[str, dict]:
    """扫描其它模块里直接读的环境变量。"""
    out: dict[str, dict] = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        if path.name == "config.py":
            continue
        text = path.read_text(encoding="utf-8")
        for match in ANY_ENV.finditer(text):
            name = match.group(1)
            if name in out:
                continue
            line = text[:match.start()].count("\n") + 1
            out[name] = {"field": "", "default": "", "where": f"{path.relative_to(ROOT).as_posix()}:{line}"}
    return out


def render() -> str:
    entries = scattered_entries()
    entries.update(settings_entries())          # config.py 的定义优先（带默认值）
    # 兜底：config.py 里有些变量不是 `字段=...` 的形状（比如 `return _first_env("LLM_API_KEY", ...)`），
    # 上面两条都扫不到。漏掉的后果是「代码认这个变量、示例里没有」，只补空壳也比漏强。
    for name in sorted(_all_env_names()):
        if name not in entries and name not in SYSTEM_ENV:
            entries[name] = {"field": "", "default": "", "where": "src/config.py"}

    buckets: dict[str, list[tuple[str, dict]]] = {}
    for env, info in entries.items():
        if env in SYSTEM_ENV:
            continue                             # 系统环境，写进示例只会误导
        title, _, _ = kind_of(env)
        buckets.setdefault(title, []).append((env, info))

    order = []
    for _, title, _ in GROUPS:
        if title not in order:
            order.append(title)
    order.append("其他")
    notes = {title: note for _, title, note in GROUPS}

    lines = [
        "# 环境变量全量清单 —— 由 tools/gen_env_example.py 从代码生成，不要手改。",
        "# 改完代码跑一遍该工具；CI 会校验本文件与代码一致（不一致就失败）。",
        "#",
        "# 优先级：设置面板（写入 appconfig.json）> 环境变量 > 代码默认值。",
        "# 面板里显式清空的项不会回落到环境变量，否则用户清不干净。",
        "",
    ]
    for title in order:
        items = sorted(buckets.get(title, []))
        if not items:
            continue
        lines.append(f"# ===== {title} =====")
        if notes.get(title):
            lines.append(f"# {notes[title]}")
        for env, info in items:
            secret = any(hint in env for hint in SECRET_HINTS)
            value = "" if secret else info["default"]
            suffix = ""
            if info["where"] != "src/config.py":
                suffix = f"   # 见 {info['where']}"
            elif not info["field"]:
                suffix = ""
            lines.append(f"# {env}={value}{suffix}".rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    check = "--check" in sys.argv[1:]
    content = render()
    if check:
        if not TARGET.exists():
            print(f"缺少 {TARGET.name}：跑 python tools/gen_env_example.py 生成")
            return 1
        current = TARGET.read_text(encoding="utf-8")
        if current != content:
            print(f"{TARGET.name} 与代码不一致，跑 python tools/gen_env_example.py 更新")
            import difflib
            diff = list(difflib.unified_diff(
                current.splitlines(), content.splitlines(),
                fromfile="磁盘上的 .env.example", tofile="按代码生成的", lineterm=""))
            print("\n".join(diff[:40]))
            return 1
        total = content.count("\n# ") - content.count("\n# =====")
        print(f"{TARGET.name} 与代码一致（{total} 个变量）")
        return 0
    TARGET.write_text(content, encoding="utf-8", newline="\n")
    count = len(re.findall(r"^# [A-Z][A-Z0-9_]*=", content, re.M))
    print(f"已写入 {TARGET.relative_to(ROOT)}（{count} 个变量）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
