"""整库备份 / 恢复：能打包、能回滚、挡 zip slip。

这组用例的锚点是「误操作之后还能不能救回来」，所以每条都真的写文件、删文件、再恢复，
而不是只断言函数返回值。
"""
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import backup  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}  {detail}")


def make_home() -> Path:
    home = Path(tempfile.mkdtemp(prefix="jiyi-backup-"))
    (home / "notes" / "2026" / "10").mkdir(parents=True)
    (home / "threads").mkdir()
    (home / "exports").mkdir()
    (home / "index").mkdir()
    (home / "notes" / "2026" / "10" / "a.md").write_text("# 甲\n内容 1\n", encoding="utf-8")
    (home / "threads" / "t1.json").write_text(json.dumps({"title": "会话"}), encoding="utf-8")
    (home / "exports" / "old.md").write_text("# 导出\n", encoding="utf-8")
    (home / "index" / "notes.jsonl").write_text("should-not-be-packed\n", encoding="utf-8")
    return home


def test_create() -> None:
    print("打包")
    home = make_home()
    result = backup.create(home, note="手动备份")
    check("返回文件名", result["name"].startswith("backup-") and result["name"].endswith(".zip"))
    check("三个文件都进包", result["files"] == 3, str(result))
    target = Path(result["path"])
    check("包真的存在", target.is_file())
    with zipfile.ZipFile(target) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
    check("含笔记", "notes/2026/10/a.md" in names, str(names))
    check("含会话", "threads/t1.json" in names)
    check("含导出", "exports/old.md" in names)
    check("不含索引", not any(n.startswith("index/") for n in names))
    check("manifest 记了说明", manifest.get("note") == "手动备份")
    backups = backup.list_backups(home)
    check("列表能看到", backups and backups[0]["name"] == result["name"], str(backups[:1]))


def test_restore() -> None:
    print("恢复")
    home = make_home()
    pack = backup.create(home, note="回滚点")
    (home / "notes" / "2026" / "10" / "a.md").write_text("# 改坏了\n", encoding="utf-8")
    (home / "threads" / "t1.json").unlink()

    try:
        backup.restore(home, pack["name"])
        check("覆盖前要求确认（409）", False, "居然直接恢复了")
    except backup.BackupError as exc:
        check("覆盖前要求确认（409）", exc.status == 409, f"status={exc.status}")

    result = backup.restore(home, pack["name"], force=True)
    check("恢复了三个文件", result["restored"] == 3, str(result))
    check("笔记回到旧版本",
          (home / "notes" / "2026" / "10" / "a.md").read_text(encoding="utf-8") == "# 甲\n内容 1\n")
    check("被删的会话回来了", (home / "threads" / "t1.json").exists())
    check("恢复前又备份了一份", bool(result.get("pre_backup")), str(result.get("pre_backup")))
    check("索引没被备份内容污染",
          (home / "index" / "notes.jsonl").read_text(encoding="utf-8") == "should-not-be-packed\n")


def test_slip_guard() -> None:
    print("路径逃逸与坏输入")
    home = make_home()
    evil = backup.backup_dir(home)
    evil.mkdir(parents=True, exist_ok=True)
    target = evil / "backup-evil.zip"
    with zipfile.ZipFile(target, "w") as zf:
        zf.writestr("../escape.md", "pwned")
    try:
        backup.restore(home, "backup-evil.zip", force=True)
        check("挡 ../ 逃逸", False, "居然解压了")
    except backup.BackupError as exc:
        check("挡 ../ 逃逸", "非法路径" in str(exc), str(exc))
    check("逃逸文件没落盘", not (home.parent / "escape.md").exists())

    try:
        backup.restore(home, "nope.zip")
        check("不存在的包报 404", False)
    except backup.BackupError as exc:
        check("不存在的包报 404", exc.status == 404, f"status={exc.status}")

    try:
        backup.restore(home, "../../etc/passwd")
        check("拒绝非 zip 名称", False)
    except backup.BackupError as exc:
        check("拒绝非 zip 名称", exc.status == 400, f"status={exc.status}")

    empty = Path(tempfile.mkdtemp(prefix="jiyi-empty-"))
    try:
        backup.create(empty)
        check("空存储区不产出空包", False)
    except backup.BackupError as exc:
        check("空存储区不产出空包", exc.status == 400, f"status={exc.status}")


def main() -> int:
    test_create()
    test_restore()
    test_slip_guard()
    print(f"\n{'全部通过' if FAILED == 0 else f'{FAILED} 项失败'}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
