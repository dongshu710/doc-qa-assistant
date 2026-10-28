#!/usr/bin/env python3
"""构建两个发布包：应用包（问答 + 笔记）与插件包（只有笔记）。

用法：
    python tools/build_release.py

产物：
    dist/jiyi-app-<version>.zip       完整服务，解压双击 start 脚本即用
    dist/jiyi-plugin-<version>.zip    只含 src/notes，挂到任意 MCP 客户端
    dist/jiyi-skill-<version>.zip     jiyi-files 技能，解压进 ~/.workbuddy/skills/
    dist/SHA256SUMS.txt                  两个包的 sha256

设计取舍：只打源码包，不做 PyInstaller 单文件。运行时零第三方依赖，
源码包更小、可审计、跨平台。插件包单独出一个，是因为「只想让智能体记笔记」的人
不该为了一个 stdio 进程去下载整套检索、索引和页面。
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

APP_PREFIX = "jiyi-app"
PLUGIN_PREFIX = "jiyi-plugin"
SKILL_PREFIX = "jiyi-skill"
SKILL_DIR = ROOT / "skills" / "jiyi-files"

INCLUDE_DIRS = ("src", "data", "docs", "tests", "tools", "deploy")
INCLUDE_FILES = (
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "VERSION",
    "pyproject.toml",
    "requirements.txt",
    ".env.example",
    "start.bat",
    "start.sh",
    "start-desktop.bat",
    "start-desktop.sh",
)

# 插件包只带笔记：MCP stdio 只需要 src/notes + 版本号
PLUGIN_DIRS = ("src/notes",)
# store.py 会读 appconfig 里的默认笔记目录，插件包也必须带上它
PLUGIN_FILES = ("src/__init__.py", "src/version.py", "src/appconfig.py", "VERSION", "LICENSE")

# 运行时产物与本地环境不进包
EXCLUDE_DIR_NAMES = {"__pycache__", ".venv", "venv", "logs", "dist", ".git", ".github",
                     "screenshots", "kb", "index"}
EXCLUDE_FILE_NAMES = {"report_doc_cases.json", "eval_cases_docs.jsonl", ".DS_Store",
                      "Thumbs.db", "e2e-server.log"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def iter_payload() -> list[Path]:
    files: list[Path] = []
    for name in INCLUDE_FILES:
        path = ROOT / name
        if not path.is_file():
            raise FileNotFoundError(f"缺少发布文件: {name}")
        files.append(path)
    for dirname in INCLUDE_DIRS:
        base = ROOT / dirname
        if not base.is_dir():
            raise FileNotFoundError(f"缺少发布目录: {dirname}")
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(ROOT).parts
            if any(part in EXCLUDE_DIR_NAMES for part in rel_parts):
                continue
            if path.name in EXCLUDE_FILE_NAMES or path.suffix in EXCLUDE_SUFFIXES:
                continue
            files.append(path)
    return files


def iter_plugin_payload() -> list[Path]:
    """插件包：notes 源码 + 版本号 + 许可证 + 一份插件专用 README。"""
    readme = ROOT / "docs" / "PLUGIN_PACKAGE.md"
    if not readme.is_file():
        raise FileNotFoundError("缺少 docs/PLUGIN_PACKAGE.md")
    files: list[Path] = [readme]
    for name in PLUGIN_FILES:
        path = ROOT / name
        if not path.is_file():
            raise FileNotFoundError(f"缺少插件文件: {name}")
        files.append(path)
    for dirname in PLUGIN_DIRS:
        base = ROOT / dirname
        if not base.is_dir():
            raise FileNotFoundError(f"缺少插件目录: {dirname}")
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix not in EXCLUDE_SUFFIXES \
                    and "__pycache__" not in path.parts:
                files.append(path)
    return files


def iter_skill_payload() -> list[Path]:
    """技能包：整个 skills/jiyi-files 目录，4 个文件，解压到技能目录即可用。"""
    if not SKILL_DIR.is_dir():
        raise FileNotFoundError(f"缺少技能目录: {SKILL_DIR}")
    files = [path for path in sorted(SKILL_DIR.rglob("*"))
             if path.is_file() and "__pycache__" not in path.parts
             and path.suffix not in EXCLUDE_SUFFIXES]
    if not files:
        raise FileNotFoundError("技能目录是空的")
    return files


def write_zip(out: Path, root_name: str, payload: list[Path],
              readme_from_docs: bool = False, base: Path = ROOT) -> Path:
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in payload:
            # 插件包的 README 来自 docs/，放进包里改叫 README.md，解压后能直接看。
            # 只在插件包这么做：应用包自带 README.md，重映射会撞名（Duplicate name）。
            if readme_from_docs and path.name == "PLUGIN_PACKAGE.md":
                arcname = f"{root_name}/README.md"
            else:
                arcname = f"{root_name}/{path.relative_to(base).as_posix()}"
            info = zipfile.ZipInfo.from_file(path, arcname)
            info.compress_type = zipfile.ZIP_DEFLATED
            # 让解压后的启动脚本直接可执行（zip 保存 Unix 权限位）
            if path.name.endswith(".sh"):
                info.external_attr = 0o755 << 16
            zf.writestr(info, path.read_bytes())
    return out


def build() -> list[Path]:
    ver = version()
    DIST.mkdir(parents=True, exist_ok=True)
    jobs = [
        {"out": DIST / f"{APP_PREFIX}-{ver}.zip", "root": f"{APP_PREFIX}-{ver}",
         "files": iter_payload(), "readme": False, "base": ROOT},
        {"out": DIST / f"{PLUGIN_PREFIX}-{ver}.zip", "root": f"{PLUGIN_PREFIX}-{ver}",
         "files": iter_plugin_payload(), "readme": True, "base": ROOT},
        # 技能包的根目录必须叫 jiyi-files（不带版本号），解压进 skills/ 才能直接被识别
        {"out": DIST / f"{SKILL_PREFIX}-{ver}.zip", "root": SKILL_DIR.name,
         "files": iter_skill_payload(), "readme": False, "base": SKILL_DIR},
    ]
    made: list[Path] = []
    lines: list[str] = []
    for job in jobs:
        out, root_name, payload = job["out"], job["root"], job["files"]
        write_zip(out, root_name, payload, job["readme"], job["base"])
        digest = hashlib.sha256(out.read_bytes()).hexdigest()
        lines.append(f"{digest}  {out.name}")
        made.append(out)
        size_mb = out.stat().st_size / 1024 / 1024
        print(f"已构建：{out}  ({len(payload)} 个文件, {size_mb:.2f} MB)")
        print(f"SHA256：{digest}")

    (DIST / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return made


def main() -> int:
    try:
        build()
    except (OSError, FileNotFoundError) as exc:
        print(f"构建失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
