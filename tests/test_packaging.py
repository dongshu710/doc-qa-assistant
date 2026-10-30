"""打包契约：pyproject 里的声明必须和仓库实际结构一致。

为什么需要这个测试：`pyproject.toml` 里的包清单、入口点、版本来源都是手写的，
新增一个子包却忘了登记时，`pip install` 出来的包会在运行时报 ImportError，
而源码目录下一切正常——这种漂移只能在安装态才暴露。
"""
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def load() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_syntax() -> None:
    print("pyproject 可解析")
    data = load()
    check("有 project 段", "project" in data)
    check("用 setuptools 后端", data["build-system"]["build-backend"] == "setuptools.build_meta")


def test_packages() -> None:
    print("包清单覆盖实际目录")
    declared = set(load()["tool"]["setuptools"]["packages"])
    actual = set()
    for init in (ROOT / "src").rglob("__init__.py"):
        rel = init.parent.relative_to(ROOT).as_posix().replace("/", ".")
        actual.add(rel)
    check("声明的包都存在", declared <= actual, f"多余: {declared - actual}")
    check("没有漏登记的包", actual <= declared, f"漏了: {actual - declared}")


def test_scripts() -> None:
    print("入口点指向真实函数")
    import importlib

    scripts = load()["project"]["scripts"]
    check("有 MCP 入口", "agent-notes-mcp" in scripts, str(list(scripts)))
    for name, target in scripts.items():
        module_path, _, func = target.partition(":")
        try:
            mod = importlib.import_module(module_path)
        except Exception as exc:  # noqa: BLE001
            check(f"{name} 模块可导入", False, f"{module_path}: {exc}")
            continue
        check(f"{name} → {target} 存在", callable(getattr(mod, func, None)),
              f"{module_path} 里没有 {func}")


def test_version() -> None:
    print("版本号单一来源")
    tool = load()["tool"]["setuptools"]["dynamic"]
    check("版本是动态读取", "version" in tool, str(tool))
    check("从 VERSION 文件读", tool["version"]["file"] == ["VERSION"], str(tool["version"]))
    check("VERSION 文件存在", (ROOT / "VERSION").is_file())
    from src.version import __version__
    check("运行期版本与 VERSION 一致",
          __version__ == (ROOT / "VERSION").read_text(encoding="utf-8").strip(), __version__)


def test_zero_deps() -> None:
    print("零依赖承诺")
    project = load()["project"]
    check("dependencies 为空", project["dependencies"] == [], str(project["dependencies"]))
    check("requires-python 下限合理", project["requires-python"] == ">=3.11",
          project["requires-python"])
    check("有 LICENSE 文件", (ROOT / "LICENSE").is_file())


def test_web_assets_packaged() -> None:
    print("前端资源会随包安装且能读到")
    conf = load()
    data = (conf["tool"]["setuptools"].get("package-data") or {}).get("src") or []
    names = sorted(p.name for p in (ROOT / "src" / "web").iterdir() if p.is_file())
    check("src/web 下有资源", bool(names), str(len(names)))
    check("package-data 覆盖 web/*", any(item.startswith("web/") for item in data), str(data))
    # 资源读取走 importlib.resources，装成包或进压缩包后仍然能读；
    # 这里直接调一遍，防止哪天又被改回 open(__file__ 相对路径)
    from src import webassets
    check("webassets 列出的资源与磁盘一致", set(webassets.names()) == set(names),
          str(set(names) ^ set(webassets.names())))
    check("每个资源都读得出内容", all(webassets.load(n) for n in names))


def main() -> int:
    test_syntax()
    test_packages()
    test_scripts()
    test_version()
    test_zero_deps()
    test_web_assets_packaged()
    print(f"\n{'全部通过' if FAILED == 0 else f'{FAILED} 项失败'}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
