"""jiyi-files 技能的可执行测试：结构、读路径、写降级、安装器。

直接跑：python tests/test_skill.py
不联网、不需要已记忆文档在跑：故意把 base_url 指到一个空端口，验证降级路径。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "jiyi-files"
JY = SKILL / "scripts" / "jy.py"
INSTALLER = ROOT / "tools" / "install_skill.py"
DEAD_BASE = "http://127.0.0.1:59999"

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"PASS {name}")
    else:
        FAIL += 1
        print(f"FAIL {name}  {detail}")


def run(*args: str, stdin: str | None = None) -> tuple[int, str, str]:
    env = {**os.environ, "PYTHONUTF8": "1"}
    proc = subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          encoding="utf-8", input=stdin, timeout=120, env=env)
    return proc.returncode, proc.stdout, proc.stderr


def note_text(note_id: str, title: str, created: str, body: str, tags: str = "示例") -> str:
    return (
        "---\n"
        "schema: note/v1\n"
        f"id: {note_id}\n"
        f"title: {title}\n"
        f"created: {created}\n"
        f"updated: {created}\n"
        "kind: qa\n"
        "status: draft\n"
        f"tags: [{tags}]\n"
        "source:\n"
        "  agent: workbuddy\n"
        "  messages: 2\n"
        "digest: rule\n"
        "---\n\n"
        f"## 摘要\n\n{body}\n"
    )


def seed_home() -> Path:
    home = Path(tempfile.mkdtemp(prefix="zy-skill-home-"))
    folder = home / "notes" / "2026" / "10"
    folder.mkdir(parents=True)
    (folder / "20261025-100000-aaaaaa.md").write_text(
        note_text("20261025-100000-aaaaaa", "赎回到账时点", "2026-10-25T10:00:00+08:00",
                  "赎回申请 T 日提交，资金 T+1 个工作日到账。"), encoding="utf-8")
    (folder / "20261025-110000-bbbbbb.md").write_text(
        note_text("20261025-110000-bbbbbb", "起购金额与风险等级", "2026-10-25T11:00:00+08:00",
                  "起购金额 1 元，风险等级 R1，期限 90 天。", tags="示例, 产品"),
        encoding="utf-8")
    return home


def test_structure() -> None:
    check("技能目录存在", SKILL.is_dir(), str(SKILL))
    for name in ("SKILL.md", "scripts/jy.py", "references/api.md", "assets/config.example.json"):
        check(f"包含 {name}", (SKILL / name).is_file())

    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    head = text.split("---")[1] if text.startswith("---") else ""
    check("frontmatter 有 name", "name: jiyi-files" in head)
    check("frontmatter 有 agent_created", "agent_created: true" in head)
    desc = next((line.split(":", 1)[1].strip() for line in head.splitlines()
                 if line.startswith("description:")), "")
    check("description 写清了触发场景", len(desc) > 40 and "笔记" in desc, desc[:40])
    check("SKILL.md 有卸载/验证说明", "doctor" in text and "save" in text)


def test_doctor_offline(home: Path) -> None:
    code, out, err = run(str(JY), "--base-url", DEAD_BASE, "--home", str(home), "doctor")
    check("服务不可用时 doctor 退出码 1", code == 1, f"exit={code}")
    check("doctor 明确标出服务 ✗", "✗ 服务" in out, out.replace("\n", " ")[:60])
    check("doctor 仍能统计篇数", "2" in out, out.replace("\n", " ")[:60])
    check("doctor 给出只能读的结论", "只能读" in out, out.replace("\n", " ")[:80])


def test_read(home: Path) -> None:
    code, out, _ = run(str(JY), "--base-url", DEAD_BASE, "--home", str(home), "list", "--json")
    data = json.loads(out)
    check("list --json 可解析", data.get("ok") is True and data.get("count") == 2, out[:80])
    check("list 按时间倒序", data["items"][0]["id"] == "20261025-110000-bbbbbb",
          str([item["id"] for item in data["items"]]))

    code, out, _ = run(str(JY), "--base-url", DEAD_BASE, "--home", str(home), "list",
                       "--tag", "产品", "--json")
    check("按标签过滤", json.loads(out)["count"] == 1, out[:80])

    code, out, _ = run(str(JY), "--base-url", DEAD_BASE, "--home", str(home), "search", "赎回")
    check("搜索命中", "命中 1 篇" in out and "赎回到账时点" in out, out[:80])

    code, out, _ = run(str(JY), "--base-url", DEAD_BASE, "--home", str(home),
                       "search", "赎回", "起购")
    check("多词是全部命中", "没有命中" in out, out[:80])

    code, out, _ = run(str(JY), "--base-url", DEAD_BASE, "--home", str(home),
                       "get", "20261025-100000-aaaaaa")
    check("按 id 读全文", code == 0 and "## 摘要" in out and "T+1" in out, out[:80])

    code, out, _ = run(str(JY), "--base-url", DEAD_BASE, "--home", str(home), "get", "不存在的")
    check("找不到时退出码 2", code == 2, f"exit={code}")

    code, out, _ = run(str(JY), "--base-url", DEAD_BASE, "--home", str(home), "open", "--no-launch")
    check("open 打印地址", code == 0 and out.strip().endswith("/files"), out.strip()[:60])


def test_write_degrades(home: Path) -> None:
    payload = json.dumps({"messages": [
        {"role": "user", "text": "技能测试：这条应该被拒绝"},
        {"role": "assistant", "text": "服务没起时应给出启动提示。"},
    ]}, ensure_ascii=False)

    code, out, err = run(str(JY), "--base-url", DEAD_BASE, "--home", str(home), "save",
                         stdin=payload)
    check("服务没起且没给源码目录时失败", code == 1, f"exit={code}")
    check("失败信息给出启动办法", "start.bat" in err, err[:100])

    offline_home = Path(tempfile.mkdtemp(prefix="zy-skill-offline-"))
    code, out, err = run(str(JY), "--base-url", DEAD_BASE, "--home", str(offline_home),
                         "--jiyi-home", str(ROOT), "save", "--title", "离线保存自检",
                         "--json", stdin=payload)
    check("给了源码目录时离线保存成功", code == 0 and '"via": "cli"' in out,
          (out or err)[:120])
    written = list((offline_home / "notes").rglob("*.md")) if (offline_home / "notes").is_dir() else []
    check("离线保存真的落了文件", len(written) == 1, str(offline_home))

    code, out, err = run(str(JY), "--base-url", DEAD_BASE, "--home", str(home), "export",
                         "--format", "html")
    check("导出在服务不可用时明确失败", code == 1 and "导出" in err, err[:100])


def test_installer() -> None:
    target = Path(tempfile.mkdtemp(prefix="zy-skill-target-")) / "skills"
    code, out, _ = run(str(INSTALLER), "--target", str(target), "--check")
    check("installer --check 可用", code == 0 and "未安装" in out, out[:80])

    code, out, _ = run(str(INSTALLER), "--target", str(target), "--no-doctor")
    check("installer 安装成功", code == 0 and (target / "jiyi-files" / "SKILL.md").is_file(),
          out[:120])

    code, out, _ = run(str(INSTALLER), "--target", str(target), "--check")
    check("installer 复查为已安装", "已安装" in out, out[:80])

    code, out, _ = run(str(INSTALLER), "--target", str(target), "--uninstall")
    check("installer 卸载成功", code == 0 and not (target / "jiyi-files").exists(), out[:120])
    backup_root = Path.home() / ".workbuddy" / "skills-backup"
    removed = sorted(backup_root.glob("jiyi-files-removed-*")) if backup_root.is_dir() else []
    check("卸载留了备份", bool(removed), str(backup_root))
    for path in removed[-1:]:
        shutil.rmtree(path, ignore_errors=True)   # 测试产物，别留在用户目录里
    shutil.rmtree(target.parent, ignore_errors=True)


def main() -> int:
    home = seed_home()
    try:
        test_structure()
        test_doctor_offline(home)
        test_read(home)
        test_write_degrades(home)
        test_installer()
    finally:
        shutil.rmtree(home, ignore_errors=True)
        for leftover in Path(tempfile.gettempdir()).glob("zy-skill-offline-*"):
            shutil.rmtree(leftover, ignore_errors=True)
    print(f"\n通过 {PASS}，失败 {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
