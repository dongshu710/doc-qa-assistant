"""存储内核与 CLI 的离线测试：不联网、不依赖 pytest，直接 python tests/test_notes_store.py。

守的是四条底线：文件能原样读回、手改后能自愈、索引删了能重建、重复内容不重复落盘。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.notes import NoteError, NoteService, NoteStore  # noqa: E402
from src.notes.store import StoreBusy  # noqa: E402

PAYLOAD = {
    "messages": [
        {"role": "user", "text": "出口退税的退税率按什么标准执行？"},
        {"role": "assistant", "text": "根据办法第十二条，退税率按出口货物适用税率执行，2026-11-01 起统一按 13% 执行。决定由财务部在每月 5 日前复核。"},
        {"role": "user", "text": "那下一步要做什么？"},
        {"role": "assistant", "text": "待办：财务部复核申报表；下一步提交税务局备案。参考 https://example.com/policy 。"},
    ],
    "hint": {"title": "出口退税申报口径确认", "kind": "decision", "tags": ["税务", "出口退税"]},
    "source": {"agent": "claude-desktop", "model": "claude-sonnet-4-5", "session": "sess_1"},
}


def md_files(home: Path) -> list[Path]:
    return sorted(home.rglob("*.md"))


def main() -> None:
    home = Path(tempfile.mkdtemp(prefix="notes-store-"))
    service = NoteService(str(home))

    # 1. 保存：路径按 年/月 分层，front matter 字段齐全
    saved = service.save(PAYLOAD)
    assert saved["committed"] is True and saved["path"], saved
    path = Path(saved["path"])
    assert path.exists(), path
    assert re.search(r"notes[\\/]\d{4}[\\/]\d{2}[\\/]" + re.escape(saved["id"]) + r"\.md$", str(path)), path
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n") and "schema: note/v1" in text and "hash: sha256:" in text, text[:200]
    print("保存与路径 OK:", path.name)

    # 2. 读回：标题/标签/类型/小节都在
    got = service.get(saved["id"])
    assert got["title"] == "出口退税申报口径确认", got["title"]
    assert got["tags"] == ["税务", "出口退税"], got["tags"]
    assert got["kind"] == "decision"
    assert got["sections"][0]["title"] == "摘要" and got["sections"][0]["body"].strip()
    print("读回 OK:", [item["title"] for item in got["sections"]])

    # 3. 手改文件：换成人类编辑器的场景，读路径必须立刻反映
    edited = text.replace("title: 出口退税申报口径确认", "title: 改过的标题")
    path.write_text(edited, encoding="utf-8")
    assert service.get(saved["id"])["title"] == "改过的标题"
    rows = service.list(limit=10)
    assert rows and rows[0]["title"] == "改过的标题", rows
    print("手改自愈 OK")

    # 4. 索引删掉：list 自动重建，条数与磁盘一致
    index_file = home / "index" / "notes.jsonl"
    index_file.unlink()
    fresh = NoteService(str(home))
    rows = fresh.list(limit=0)
    assert len(rows) == len(md_files(home)) == 1, (len(rows), md_files(home))
    assert index_file.exists()
    print("索引重建 OK:", len(rows), "篇")

    # 5. 重复保存：同内容不产生第二个文件
    again = service.save(PAYLOAD)
    assert again["duplicate_of"] == saved["id"], again
    assert again["id"] == saved["id"] and again["committed"] is False
    assert len(md_files(home)) == 1, md_files(home)
    print("去重 OK:", again["duplicate_of"])

    # 6. 没写 front matter 的外部文件：不报错，标 external
    manual = home / "notes" / "2026" / "10" / "manual001.md"
    manual.parent.mkdir(parents=True, exist_ok=True)
    manual.write_text("# 手工加的笔记\n\n这是我自己写的内容。\n", encoding="utf-8")
    external = service.store.get("manual001")
    assert external.external is True and external.title.startswith("手工加的笔记"), external
    print("外部文件容错 OK:", external.title)

    # 7. front matter 坏掉：仍然能读出正文
    broken = home / "notes" / "2026" / "10" / "broken01.md"
    broken.write_text("---\ntitle: 坏掉的\noops 这一行没有冒号\n---\n\n## 摘要\n\n正文还在。\n", encoding="utf-8")
    parsed = service.store.get("broken01")
    assert parsed.external is True and parsed.section("摘要") == "正文还在。", parsed
    print("坏格式容错 OK")

    # 8. 选择：只存第 2 条、按关键词存
    one = service.save({**PAYLOAD, "select": {"mode": "indices", "indices": [2]},
                        "hint": {"title": "只存第二条"}})
    assert one["messages"] == 1 and "13%" in one["markdown"], one
    keyword = service.save({**PAYLOAD, "select": {"mode": "keyword", "keyword": "备案"},
                            "hint": {"title": "按关键词"}})
    assert keyword["messages"] == 1
    print("选择模式 OK")

    # 9. 原文默认不存，显式开启才存
    assert "## 原文" not in one["markdown"]
    with_raw = service.save({**PAYLOAD, "hint": {"title": "带原文"}}, keep_raw=True)
    assert "## 原文" in with_raw["markdown"] and "**用户**" in with_raw["markdown"]
    print("原文开关 OK")

    # 10. 删除是软删除，能找回
    removed = service.store.delete(saved["id"])
    assert removed.exists() and removed.parent.name == ".trash", removed
    assert all(row["id"] != saved["id"] for row in service.list(limit=0))
    print("软删除 OK:", removed.name)

    # 11. 锁：已有写入时给出明确错误而不是死等
    lock_dir = home / ".lock"
    lock_dir.mkdir(exist_ok=True)
    try:
        with service.store.lock(timeout=0.2):
            raise AssertionError("不该拿到锁")
    except StoreBusy as exc:
        assert "写入" in str(exc)
    finally:
        lock_dir.rmdir()
    print("目录锁 OK")

    # 12. 非法输入要给人话
    for bad, keyword in (
        ({}, "messages"),
        ({"messages": []}, "为空"),
        ({"messages": [{"role": "user", "text": "   "}]}, "为空"),
        ({**PAYLOAD, "select": {"mode": "indices", "indices": [99]}}, "超出范围"),
        ({**PAYLOAD, "select": {"mode": "range", "start": 3, "end": 1}}, "不合法"),
        ({**PAYLOAD, "select": {"mode": "wat"}}, "未知"),
        ({**PAYLOAD, "digest": "llm"}, "规则摘要"),
    ):
        try:
            service.save(bad, commit=False)
            raise AssertionError(f"应当报错：{bad}")
        except NoteError as exc:
            assert keyword in str(exc), (bad, str(exc))
    print("错误信息 OK")

    # 13. 统计
    stats = service.stats()
    assert stats["notes"] == len(service.list(limit=0)) >= 2 and stats["kinds"], stats
    print("统计 OK:", stats["notes"], "篇")

    # 14. CLI：任何只能跑命令的智能体都能用
    cli_home = Path(tempfile.mkdtemp(prefix="notes-cli-"))
    payload_file = cli_home / "conv.json"
    payload_file.write_text(json.dumps(PAYLOAD, ensure_ascii=False), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"}
    base = [sys.executable, "-m", "src.notes", "--home", str(cli_home / "store")]
    run = subprocess.run(base + ["save", "--from", str(payload_file), "--json"],
                         capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(ROOT))
    assert run.returncode == 0, run.stderr
    cli_saved = json.loads(run.stdout)
    assert cli_saved["ok"] and Path(cli_saved["path"]).exists(), cli_saved

    listed = subprocess.run(base + ["list", "--json"], capture_output=True, text=True,
                            encoding="utf-8", env=env, cwd=str(ROOT))
    assert listed.returncode == 0, listed.stderr
    assert len(json.loads(listed.stdout)) == 1

    draft = subprocess.run(base + ["save", "--from", str(payload_file), "--draft"],
                           capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(ROOT))
    assert draft.returncode == 0 and "草稿" in draft.stdout, draft.stdout

    bad_file = cli_home / "bad.json"
    bad_file.write_text("{not json", encoding="utf-8")
    failed = subprocess.run(base + ["save", "--from", str(bad_file)],
                            capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(ROOT))
    assert failed.returncode == 2 and "JSON" in failed.stderr, failed.stderr
    print("CLI OK")

    print("\nNOTES STORE OK")


if __name__ == "__main__":
    main()
