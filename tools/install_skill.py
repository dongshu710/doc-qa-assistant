#!/usr/bin/env python3
"""把 jiyi-files 技能装进 WorkBuddy 的用户技能目录（零第三方依赖）。

用法：
    python tools/install_skill.py                 # 安装（已有旧版先备份）
    python tools/install_skill.py --check         # 只检查状态，不动文件
    python tools/install_skill.py --uninstall     # 卸载（先备份再删）
    python tools/install_skill.py --target D:/某处/skills

为什么不用「复制粘贴文件夹」了事：用户会忘、会复制到错的层级（多一层 jiyi-files/jiyi-files），
装完也不知道成没成。这里把备份、层级校验、装完自检一次做完。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills" / "jiyi-files"
DEFAULT_TARGET = Path.home() / ".workbuddy" / "skills"
BACKUP_ROOT = Path.home() / ".workbuddy" / "skills-backup"
NAME = "jiyi-files"
REQUIRED = ("SKILL.md", "scripts/jy.py")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def source_files() -> list[Path]:
    return sorted(path for path in SOURCE.rglob("*")
                  if path.is_file() and "__pycache__" not in path.parts)


def check_source() -> None:
    if not SOURCE.is_dir():
        raise SystemExit(f"找不到技能源码：{SOURCE}")
    for name in REQUIRED:
        if not (SOURCE / name).is_file():
            raise SystemExit(f"技能不完整，缺 {name}（{SOURCE}）")


def print_tree(files: list[Path], base: Path) -> None:
    for path in files:
        print(f"  {path.relative_to(base).as_posix()}")


def cmd_check(target: Path) -> int:
    check_source()
    installed = target / NAME
    print(f"源码：{SOURCE}（{len(source_files())} 个文件）")
    print(f"安装位置：{installed}")
    if installed.is_dir():
        same = sorted(p.relative_to(SOURCE).as_posix() for p in source_files()) == \
               sorted(p.relative_to(installed).as_posix() for p in installed.rglob("*")
                      if p.is_file() and "__pycache__" not in p.parts)
        print(f"状态：已安装（文件{'一致' if same else '与源码不同，建议重装'}）")
    else:
        print("状态：未安装")
    print("自检：python " + str(installed / "scripts" / "jy.py") + " doctor")
    return 0


def cmd_install(target: Path) -> int:
    check_source()
    target.mkdir(parents=True, exist_ok=True)
    dest = target / NAME
    if dest.exists():
        backup = BACKUP_ROOT / f"{NAME}-{stamp()}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(dest, backup)
        print(f"已备份旧版本 → {backup}")
        shutil.rmtree(dest)

    shutil.copytree(SOURCE, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    files = source_files()
    print(f"已安装到 {dest}（{len(files)} 个文件）")
    print_tree([dest / p.relative_to(SOURCE) for p in files], dest)
    print("\n下一步：")
    print("  1) 在 WorkBuddy 技能列表里刷新（多数版本会自动发现新目录；没看到就重启客户端）")
    print("  2) 跑一次自检：python " + str(dest / "scripts" / "jy.py") + " doctor")
    return 0


def cmd_uninstall(target: Path) -> int:
    dest = target / NAME
    if not dest.is_dir():
        print(f"没装过（{dest} 不存在），无需卸载")
        return 0
    backup = BACKUP_ROOT / f"{NAME}-removed-{stamp()}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dest, backup)
    shutil.rmtree(dest)
    print(f"已卸载 {dest}")
    print(f"备份留在 {backup}（想恢复就把它复制回 {target}）")
    return 0


def run_doctor(dest: Path) -> None:
    script = dest / "scripts" / "jy.py"
    if not script.is_file():
        return
    sys.stdout.flush()          # 先把自己打印完，否则子进程输出会插到前面
    print("\n— 安装后自检 —", flush=True)
    proc = subprocess.run([sys.executable, str(script), "doctor"], text=True,
                          encoding="utf-8", timeout=60)
    print(f"（退出码 {proc.returncode}：0 = 服务在跑且目录可写；1 = 请按上面的 ✗ 逐项处理）")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="安装 / 卸载 jiyi-files 技能")
    parser.add_argument("--target", default=str(DEFAULT_TARGET), help="技能目录，默认 ~/.workbuddy/skills")
    parser.add_argument("--check", action="store_true", help="只检查状态")
    parser.add_argument("--uninstall", action="store_true", help="卸载")
    parser.add_argument("--no-doctor", action="store_true", help="安装后不跑自检")
    args = parser.parse_args(argv)
    target = Path(args.target).expanduser()

    if args.check:
        return cmd_check(target)
    if args.uninstall:
        return cmd_uninstall(target)
    code = cmd_install(target)
    if not args.no_doctor:
        run_doctor(target / NAME)
    return code


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    raise SystemExit(main(sys.argv[1:]))
