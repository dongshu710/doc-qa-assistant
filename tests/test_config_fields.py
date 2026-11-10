"""配置字段与代码的一致性门禁。

这个文件存在的理由，是三类「不会报错、只会静默出错」的问题：

1. 用 `getattr(settings, "字段名", 默认值)` 读配置时，字段改名不会报错，
   只会永远读到默认值——功能看着正常，改配置永远不生效。
2. `Settings` 里新增了字段但 `load_settings()` 忘了赋值，那字段永远是 dataclass 默认。
3. 代码里新读一个环境变量，却没登记进 `.env.example`，用户永远不知道有这个东西。

三条都靠「拿代码当真相、拿清单当被检查方」来抓，不靠人记。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILED = 0

# 这些不是「本项目的配置」，是操作系统或启动方式给的，不该出现在示例文件里
SYSTEM_ENV = {"APP_CONFIG", "APPDATA", "USERNAME", "PATH", "PYTHONPATH", "HOME", "TEMP", "TMP"}

GETATTR = re.compile(r'getattr\(\s*([^,]+?)\s*,\s*["\']([a-z_0-9]+)["\']\s*,')
ANY_ENV = re.compile(
    r'(?:os\.getenv|os\.environ\.get|_first_env|_env_int|_env_float|getenv|_env_flag)'
    r'\(\s*["\']([A-Z][A-Z0-9_]+)["\']')
SETTINGS_OBJECT = re.compile(r'(?:^|[\s.(])settings$|load_settings\(\)')


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def settings_fields() -> list[str]:
    tree = ast.parse((ROOT / "src" / "config.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            return [item.target.id for item in node.body
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)]
    raise SystemExit("没找到 Settings 类：config.py 结构变了，这个门禁要跟着改")


def test_getattr_fields_exist(fields: list[str]) -> None:
    print("getattr 读的字段必须真的存在于 Settings")
    known = set(fields)
    bad = []
    read = 0
    for path in sorted((ROOT / "src").rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in GETATTR.finditer(line):
                obj, field = match.group(1), match.group(2)
                if not SETTINGS_OBJECT.search(obj):
                    continue
                read += 1
                if field not in known:
                    bad.append(f"{path.relative_to(ROOT).as_posix()}:{lineno} 读 {field}")
    check(f"扫到 {read} 处 getattr 配置读取", read > 20, str(read))
    check("没有拼错或过期的字段名", not bad, "; ".join(bad[:6]))


def test_all_fields_assigned(fields: list[str]) -> None:
    print("Settings 的每个字段都要在 load_settings 里被赋值")
    text = (ROOT / "src" / "config.py").read_text(encoding="utf-8")
    assigned = set(re.findall(r"^\s{8}([a-z_0-9]+)=", text, re.M))
    missing = [field for field in fields if field not in assigned]
    check(f"{len(fields)} 个字段全部赋值", not missing, ", ".join(missing))


def test_env_registered() -> None:
    print("代码读的每个环境变量都要出现在 .env.example")
    example = (ROOT / ".env.example")
    if not example.exists():
        check("存在 .env.example", False, "跑 python tools/gen_env_example.py 生成")
        return
    listed = set(re.findall(r"^# ([A-Z][A-Z0-9_]*)=", example.read_text(encoding="utf-8"), re.M))
    used = set()
    for path in sorted((ROOT / "src").rglob("*.py")):
        used |= set(ANY_ENV.findall(path.read_text(encoding="utf-8")))
    used -= SYSTEM_ENV
    missing = sorted(used - listed)
    extra = sorted(listed - used)
    check(f"代码用了 {len(used)} 个变量，全部已登记", not missing, ", ".join(missing))
    check("清单里没有已经不存在的变量", not extra, ", ".join(extra))


def test_example_matches_code() -> None:
    print(".env.example 与生成器输出逐字节一致")
    from tools.gen_env_example import render  # noqa: PLC0415
    expected = render()
    actual = (ROOT / ".env.example").read_text(encoding="utf-8")
    check("文件没有手工改动过", actual == expected,
          "跑 python tools/gen_env_example.py 重新生成")


def test_no_secret_in_example() -> None:
    print("示例文件里不许出现真实密钥")
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    leaks = []
    for line in text.splitlines():
        match = re.match(r"^# ([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)=(.+)$", line)
        if match and match.group(2).split("#")[0].strip():
            leaks.append(match.group(1))
    check("敏感变量一律留空", not leaks, ", ".join(leaks))


def main() -> int:
    fields = settings_fields()
    print(f"Settings 共 {len(fields)} 个字段\n")
    test_getattr_fields_exist(fields)
    test_all_fields_assigned(fields)
    test_env_registered()
    test_example_matches_code()
    test_no_secret_in_example()
    print()
    if FAILED:
        print(f"CONFIG FIELDS FAILED: {FAILED}")
        return 1
    print("CONFIG FIELDS OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
