#!/usr/bin/env python3
"""构建可下载的发布包（源码 + 演示知识库 + 启动脚本）。

用法：
    python tools/build_release.py

产物：
    dist/doc-qa-assistant-<version>.zip
    dist/SHA256SUMS.txt

设计取舍：只打源码包，不做 PyInstaller 单文件。原因是运行时零第三方依赖，
源码包更小、可审计、跨平台；双击 start.bat / sh start.sh 即可启动。
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

INCLUDE_DIRS = ("src", "data", "docs", "tests", "tools")
INCLUDE_FILES = (
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "VERSION",
    "requirements.txt",
    ".env.example",
    "start.bat",
    "start.sh",
)

# 运行时产物与本地环境不进包
EXCLUDE_DIR_NAMES = {"__pycache__", ".venv", "venv", "logs", "dist", ".git", ".github", "screenshots"}
EXCLUDE_FILE_NAMES = {"report_doc_cases.json", "eval_cases_docs.jsonl", ".DS_Store", "Thumbs.db"}
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


def build() -> Path:
    ver = version()
    name = f"doc-qa-assistant-{ver}"
    DIST.mkdir(parents=True, exist_ok=True)
    out = DIST / f"{name}.zip"
    payload = iter_payload()

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in payload:
            arcname = f"{name}/{path.relative_to(ROOT).as_posix()}"
            info = zipfile.ZipInfo.from_file(path, arcname)
            info.compress_type = zipfile.ZIP_DEFLATED
            # 让解压后的 start.sh 直接可执行（zip 保存 Unix 权限位）
            if path.name == "start.sh":
                info.external_attr = 0o755 << 16
            zf.writestr(info, path.read_bytes())

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (DIST / "SHA256SUMS.txt").write_text(f"{digest}  {out.name}\n", encoding="utf-8")

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"已构建：{out}  ({len(payload)} 个文件, {size_mb:.2f} MB)")
    print(f"SHA256：{digest}")
    return out


def main() -> int:
    try:
        build()
    except (OSError, FileNotFoundError) as exc:
        print(f"构建失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
